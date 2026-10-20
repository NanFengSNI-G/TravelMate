import pytest
from sqlalchemy import select
from app.conversations import history, select_option
from app.contracts import Request, PlanDesign
from app.db import sessions
from app.domain import Domain
from app.graph import build_graph, business_route
from app.models import Case, Proposal
from app.runs import Runs
from app.worker import process
from tests.test_graph import conversation


@pytest.mark.parametrize(
    "intent,node",
    [
        ("book", "prepare"),
        ("change", "prepare"),
        ("cancel", "prepare"),
        ("policy", "policy"),
        ("chat", "customer"),
        ("orders", "customer"),
        ("plans", "customer"),
        ("search", "search"),
        ("plan", "planning"),
        ("repair", "repair"),
    ],
)
def test_routes_follow_business(intent, node):
    assert business_route({"request": {"intent": intent}}) == node
    assert business_route({"stopped": True}) == "finish"


def test_selection_uses_server_returned_option():
    entries = [
        {
            "run_id": "run-1",
            "result": {
                "plan": {
                    "options": [
                        {
                            "resource_ids": ["f1", "h1"],
                            "start": "2030-01-01",
                            "end": "2030-01-03",
                        },
                        {
                            "resource_ids": ["f2", "h2"],
                            "start": "2030-01-01",
                            "end": "2030-01-03",
                        },
                    ]
                }
            },
        }
    ]
    request = select_option(Request(intent="book", people=2), entries, 2)
    assert request.resource_ids == ["f2", "h2"] and request.people == 2
    assert request.option_id == "run-1:2"
    newer = {
        "run_id": "run-2",
        "result": {
            "plan": {
                "options": [
                    {
                        "resource_ids": ["f3", "h3"],
                        "start": "2030-02-01",
                        "end": "2030-02-03",
                    }
                ]
            }
        },
    }
    previous = select_option(
        Request(intent="book", option_id="run-1:2"), [*entries, newer]
    )
    assert previous.resource_ids == ["f2", "h2"]
    with pytest.raises(ValueError):
        select_option(Request(intent="book", option_id="other-user:1"), entries)


def test_plan_rejects_hallucinated_pair_or_unreferenced_activity():
    req = Request(intent="plan", start="2030-01-01", end="2030-01-03")
    draft = {
        "options": [
            {"resource_ids": ["f", "h"], "amount": 100, "evidence": {"evidence": []}}
        ]
    }
    for option in (
        {"resource_ids": ["f", "invented"], "label": "A", "explanation": "test"},
        {
            "resource_ids": ["f", "h"],
            "label": "A",
            "explanation": "test",
            "days": [
                {"date": "2030-01-01", "activity": "无出处活动", "evidence_ids": []}
            ],
        },
    ):
        with pytest.raises(ValueError):
            Domain(None).validate_plan(
                req, draft, PlanDesign(options=[option]), "run-1"
            )


def test_pending_allows_read_but_blocks_second_write_and_old_confirmation(
    db_env, saver
):
    runs, domain = Runs(), Domain(None)
    cid = conversation()
    graph = build_graph(domain, saver)
    rid = runs.submit(
        "alice",
        cid,
        Request(intent="support", question="请人工核查").model_dump(mode="json"),
    )
    process(runs.claim(), graph, runs)
    assert runs.get("alice", rid).status == "WAITING"
    with sessions()() as s:
        assert not list(s.scalars(select(Case)))
    with pytest.raises(ValueError, match="待确认提案"):
        runs.submit("alice", cid, Request(intent="support").model_dump(mode="json"))
    read_id = runs.submit(
        "alice",
        cid,
        Request(
            intent="search",
            resource_kinds=["hotel"],
            start="2030-01-01",
            end="2030-01-03",
        ).model_dump(mode="json"),
    )
    process(runs.claim(), graph, runs)
    read = runs.get("alice", read_id)
    assert read.status == "DONE" and set(read.result["results"]) == {"hotel"}
    assert runs.get("alice", rid).status == "WAITING"
    runs.cancel("alice", rid)
    with pytest.raises(ValueError):
        runs.resume("alice", rid, {"decision": "approve", "version": 1})
    with sessions()() as s:
        assert not list(s.scalars(select(Case)))
        assert s.get(Proposal, rid).status == "REJECTED"


def test_support_resume_with_new_graph_and_canonical_history(db_env, saver):
    runs = Runs()
    cid = conversation()
    rid = runs.submit(
        "alice",
        cid,
        Request(intent="support", question="请人工协助").model_dump(mode="json"),
        "请人工协助",
    )
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    entries = history("alice", cid)
    assert entries[0]["status"] == "WAITING" and entries[0]["result"]["approval"]
    with pytest.raises(ValueError):
        history("bob", cid)
    runs.resume("alice", rid, {"decision": "approve", "version": 1})
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    assert runs.get("alice", rid).status == "DONE"
    assert history("alice", cid)[0]["result"]["case_id"] == rid
    with sessions()() as s:
        assert len(list(s.scalars(select(Case)))) == 1


def test_conversation_messages_preserve_roles_original_text_and_results():
    from app.conversations import messages

    history = [
        {
            "run_id": "r1",
            "text": "我叫林舟，想看已有行程",
            "request": {"intent": "plans"},
            "result": {
                "customer": {"answer": "已找到您的行程", "trace": "private"},
                "plan": {"id": "plan-1"},
            },
        }
    ]
    turns = messages(history, "我刚才想看什么？", "r2")
    assert [m.type for m in turns] == ["human", "ai", "human"]
    assert turns[0].content == history[0]["text"]
    assert "plan-1" in turns[1].content and "private" not in turns[1].content
    assert '"intent": "plans"' in turns[1].content
    assert turns[-1].id == "r2:user"


def test_saved_plan_query_and_conversation_isolation(db_env, saver):
    from app.models import Plan
    from app.conversations import messages

    with sessions().begin() as s:
        s.add(Plan(id="alice-plan", owner="alice", options=[{"label": "仅属于 Alice"}]))
        s.add(Plan(id="bob-plan", owner="bob", options=[]))
    assert [p["id"] for p in Domain(None).plans("alice")] == ["alice-plan"]
    assert [p["id"] for p in Domain(None).plans("bob")] == ["bob-plan"]
    runs = Runs()
    cid = conversation()
    rid = runs.submit(
        "alice",
        cid,
        Request(intent="support", question="记住这次服务问题").model_dump(mode="json"),
    )
    graph = build_graph(Domain(None), saver)
    process(runs.claim(), graph, runs)
    runs.resume("alice", rid, {"decision": "reject", "version": 1})
    process(runs.claim(), graph, runs)
    snapshot = graph.get_state({"configurable": {"thread_id": rid}})
    assert [m.type for m in snapshot.values["messages"]] == ["human", "ai"]
    other = conversation()
    assert messages(history("alice", other)) == []
    assert "记住这次服务问题" in messages(history("alice", cid))[0].content


@pytest.mark.live
def test_real_model_remembers_previous_turn_after_new_graph(db_env, saver):
    from app.agents import classify

    runs, cid = Runs(), conversation()
    for text in ("我叫林舟，请记住我的名字。", "我刚才告诉你我叫什么？"):
        request = classify(text, history("alice", cid))
        assert request.intent == "chat"
        rid = runs.submit("alice", cid, request.model_dump(mode="json"), text)
        process(runs.claim(), build_graph(Domain(None), saver), runs)
    assert "林舟" in runs.get("alice", rid).result["customer"]["answer"]


@pytest.mark.live
def test_real_followup_resolution_and_saved_plan_tool(db_env, saver):
    from app.agents import classify
    from app.models import Plan

    entries = [
        {
            "text": "我已有行程",
            "result": {"customer": {"answer": "需要查看已有行程吗？"}},
        }
    ]
    request = classify("我想看看", entries)
    assert request.intent == "plans"
    with sessions().begin() as s:
        s.add(
            Plan(id="remembered-plan", owner="alice", options=[{"label": "上海三日"}])
        )
    runs, cid = Runs(), conversation()
    rid = runs.submit("alice", cid, request.model_dump(mode="json"), "我想看看")
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    trace = runs.get("alice", rid).result["customer"]["trace"]
    assert any(c["name"] == "get_my_plans" for m in trace for c in m["calls"])
    followup = classify(
        "那酒店呢？",
        [
            {
                "text": "航班取消费多少？",
                "request": {"intent": "policy", "resource_ids": ["flight-0"]},
                "result": {"customer": {"answer": "航班按人收费"}},
            }
        ],
    )
    assert followup.intent == "policy"
    assert "酒店" in followup.resolved_question and "取消" in followup.resolved_question
    assert "flight-0" not in followup.resource_ids


def test_chat_context_does_not_invent_trip_defaults():
    from app.conversations import messages, prompt_request

    default = Request(intent="chat", question="你好，我是南风").model_dump(mode="json")
    assert prompt_request(default) == {}
    turns = messages(
        [
            {
                "text": "你好，我是南风",
                "request": default,
                "result": {"customer": {"answer": "你好，南风"}},
            }
        ],
        "你有哪些功能？",
    )
    assert all("北京" not in m.content and "600000" not in m.content for m in turns)


@pytest.mark.live
@pytest.mark.parametrize(
    "menu,selection",
    [
        (
            "1. 政策咨询\n2. 行程规划\n3. 资源查询\n4. 订单管理：查看当前订单状态\n5. 人工服务",
            "4",
        ),
        ("1. 人工服务\n2. 查看本人订单\n3. 政策咨询", "2"),
    ],
)
def test_real_number_selects_last_assistant_menu(menu, selection, db_env):
    from app.agents import classify, Agents

    entries = [
        {
            "text": "你好，我是南风",
            "request": Request(intent="chat").model_dump(mode="json"),
            "result": {"customer": {"answer": "你好，南风"}},
        },
        {
            "text": "你有哪些功能，我叫什么名字",
            "request": Request(intent="chat").model_dump(mode="json"),
            "result": {"customer": {"answer": "南风，我的功能有：\n" + menu}},
        },
    ]
    req = classify(selection, entries)
    assert req.intent == "orders"
    assert req.question == selection
    assert req.people == 1
    assert req.resolved_question and "订单" in req.resolved_question
    result = Agents(Domain(None)).customer("alice", req, entries)
    assert any(
        call["name"] == "get_my_orders" for m in result["trace"] for call in m["calls"]
    )


def test_plan_combination_identity_ignores_resource_order():
    req = Request(intent="plan", start="2030-01-01", end="2030-01-03")
    draft = {
        "options": [
            {
                "resource_ids": ["flight", "hotel"],
                "amount": 100,
                "evidence": {"evidence": []},
            }
        ]
    }
    design = PlanDesign(
        options=[
            {
                "resource_ids": ["hotel", "flight"],
                "label": "A",
                "explanation": "有效组合",
            }
        ]
    )
    result = Domain(None).validate_plan(req, draft, design, "r")
    assert result["options"][0]["resource_ids"] == ["flight", "hotel"]
    duplicate = PlanDesign(options=[*design.options, design.options[0]])
    with pytest.raises(ValueError, match="重复"):
        Domain(None).validate_plan(req, draft, duplicate, "r")


def test_retry_keeps_original_conversation_and_requires_new_approval(db_env, saver):
    from fastapi.testclient import TestClient
    from app.api import app
    from app.auth import token

    runs = Runs()
    cid = conversation()
    original = runs.submit(
        "alice",
        cid,
        Request(intent="support", question="体验申请").model_dump(mode="json"),
    )
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    client = TestClient(app)
    alice = {"Authorization": "Bearer " + token("alice")}
    bob = {"Authorization": "Bearer " + token("bob")}
    assert (
        client.post(f"/api/runs/{original}/retry", headers=bob, json={}).status_code
        == 409
    )
    response = client.post(f"/api/runs/{original}/retry", headers=alice, json={})
    assert response.status_code == 200
    retry = runs.get("alice", response.json()["run_id"])
    assert (
        retry.conversation == cid
        and retry.payload == runs.get("alice", original).payload
    )
    assert runs.get("alice", original).status == "CANCELLED"
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    assert runs.get("alice", retry.id).status == "WAITING"
    with sessions()() as s:
        assert not list(s.scalars(select(Case)))


def test_policy_requires_explicit_scope(db_env, saver):
    runs = Runs()
    cid = conversation()
    rid = runs.submit(
        "alice",
        cid,
        Request(intent="policy", question="取消多少钱").model_dump(mode="json"),
    )
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    result = runs.get("alice", rid)
    assert result.status == "DONE"
    assert {r["id"] for r in result.result["policy_choices"]} >= {"flight-0", "hotel-0"}
    with pytest.raises(ValueError, match="指定"):
        Domain(None).evidence("alice", Request(intent="policy"))


def test_customer_case_followup_requires_confirmation_and_ownership(db_env, saver):
    runs = Runs()
    with sessions().begin() as s:
        s.add(
            Case(
                id="followup-case",
                owner="alice",
                request_id="first",
                context={"request": {"question": "原申请"}},
                status="OPEN",
                replies=[],
            )
        )
    cid = conversation()
    rid = runs.submit(
        "alice",
        cid,
        Request(
            intent="support", case_id="followup-case", question="补充出行条件"
        ).model_dump(mode="json"),
    )
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    assert runs.get("alice", rid).status == "WAITING"
    with sessions()() as s:
        assert s.get(Case, "followup-case").replies == []
    with pytest.raises(ValueError, match="不存在"):
        Domain(None).support_case("bob", "followup-case")
    runs.resume("alice", rid, {"decision": "approve", "version": 1})
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    with sessions().begin() as s:
        case = s.get(Case, "followup-case")
        assert len(case.replies) == 1 and case.replies[0]["role"] == "user"
        case.status = "CLOSED"
    other = runs.submit(
        "alice",
        cid,
        Request(
            intent="support", case_id="followup-case", question="关闭后不可补充"
        ).model_dump(mode="json"),
    )
    process(runs.claim(), build_graph(Domain(None), saver), runs)
    assert "已结束" in runs.get("alice", other).result["message"]
    with sessions()() as s:
        assert len(s.get(Case, "followup-case").replies) == 1


def test_repair_option_selection_uses_the_report_not_an_older_plan():
    entries = [
        {
            "run_id": "repair-run",
            "result": {
                "repair": {
                    "options": [
                        {
                            "resource_ids": ["f1", "h1"],
                            "start": "2030-01-01",
                            "end": "2030-01-03",
                        },
                        {
                            "resource_ids": ["f1", "h2"],
                            "start": "2030-01-01",
                            "end": "2030-01-03",
                        },
                    ]
                }
            },
        }
    ]
    result = select_option(Request(intent="book"), entries, 2)
    assert result.resource_ids == ["f1", "h2"] and result.option_id == "repair-run:2"
