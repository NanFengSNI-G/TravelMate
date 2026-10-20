import pytest

from datetime import date
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.node_parser import get_leaf_nodes
from llama_index.core.schema import TextNode, NodeWithScore, QueryBundle
from app.encoding import embedding, reranker
from app.agents import Agents, model
from app.domain import Domain
from app.knowledge import Knowledge
from app.contracts import Query, Request, EvidenceBundle


def test_native_reader_parser_limits_and_code_fences(env, tmp_path):
    path = tmp_path / "long.md"
    path.write_text(
        "# 政策\n\n## 长条款\n"
        + "取消要核对订单与日期。" * 300
        + "\n\n```markdown\n## 代码中的标题\n```\n"
    )
    result = env.import_document(
        path,
        {
            "document": "long-policy",
            "supplier": "演示酒店",
            "product": "standard",
            "valid_from": "2035-01-01",
            "valid_to": "2099-12-31",
            "rules": {"cancel_fee_cents": 5000},
        },
    )
    store = SimpleDocumentStore.from_persist_path(
        str(env.root / result["revision"] / "docstore.json")
    )
    leaves = get_leaf_nodes(list(store.docs.values()))
    assert len(leaves) > 2
    from llama_index.core.utils import get_tokenizer

    assert all(len(get_tokenizer()(n.text)) <= 64 for n in leaves)
    assert all(n.metadata["section"] != "代码中的标题" for n in leaves)
    assert all(n.parent_node for n in leaves)


def test_native_docstore_reloads_for_retrieval(env):
    query = Query(
        question="取消费",
        supplier="演示酒店",
        product="standard",
        applicable_date=date.today(),
    )
    before = env.retrieve(query)
    restarted = Knowledge(
        client=env.client, embed=embedding(), collection=env.collection
    )
    after = restarted.retrieve(query)
    assert before.snapshot == after.snapshot
    assert {e.node_id for e in before.evidence} == {e.node_id for e in after.evidence}


def test_customer_receives_canonical_context(env):
    agents = Agents(Domain(env))
    req = Request(intent="chat", question="我之前的方案多少钱？")
    result = agents.customer(
        "alice",
        req,
        [{"text": "规划行程", "result": {"plan": {"options": [{"amount": 123400}]}}}],
    )
    assert result["answer"]
    assert result["trace"][0]["role"] == "human"
    assert result["trace"][1]["role"] == "ai"
    assert "123400" in result["trace"][1]["content"]


def test_native_summarization_runs_in_agent_loop(saver):
    agent = create_agent(
        model(),
        tools=[],
        checkpointer=saver,
        middleware=[
            SummarizationMiddleware(
                model=model(),
                trigger=("messages", 6),
                keep=("messages", 2),
            )
        ],
    )
    cfg = {"configurable": {"thread_id": __import__("uuid").uuid4().hex}}
    for i in range(5):
        result = agent.invoke({"messages": [("user", f"第{i}条需求")]}, cfg)
    assert any(m.type == "system" for m in result["messages"])
    assert len(result["messages"]) < 10


@pytest.mark.live
@pytest.mark.integration
def test_native_reranker_service():
    nodes = [
        NodeWithScore(node=TextNode(id_="location", text="酒店位于上海市中心。")),
        NodeWithScore(node=TextNode(id_="cancel", text="酒店取消费用为五十元。")),
    ]
    result = reranker(top_n=1).postprocess_nodes(
        nodes, query_bundle=QueryBundle("酒店取消多少钱？")
    )
    assert result[0].node.node_id == "cancel" and result[0].score is not None


def test_insufficient_evidence_does_not_generate(env):
    result = env.answer(
        "取消费", EvidenceBundle(status="INSUFFICIENT", snapshot=[], evidence=[])
    )
    assert "不足" in result["answer"] or "没有足够" in result["answer"]


def test_native_evaluator_on_fixed_queries(env, tmp_path):
    from scripts.evaluate import evaluate

    result = evaluate(env, tmp_path / "retrieval.json")
    assert len(result["summary"]) == 4 and len(result["rows"]) == 240
    assert all(row["out_of_scope_rejection"] == 1 for row in result["summary"])
    assert any(row["mode"] == "sparse" for row in result["summary"])


def test_native_sse_reconnect_cursor(env):
    import json
    from fastapi.testclient import TestClient
    from app.api import app
    from app.models import Conversation
    from app.db import sessions
    from app.runs import Runs

    client = TestClient(app)
    response = client.post(
        "/api/login", json={"name": "alice", "password": "tutorial123"}
    )
    headers = {"Authorization": "Bearer " + response.json()["token"]}
    with sessions().begin() as s:
        c = Conversation(owner="alice")
        s.add(c)
        s.flush()
        cid = c.id
    runs = Runs()
    rid = runs.submit("alice", cid, Request(intent="policy").model_dump(mode="json"))
    run = runs.claim()
    runs.event(rid, run.fence, "progress", {"step": 1})
    runs.event(rid, run.fence, "result", {"step": 2})
    runs.complete(rid, run.fence, "DONE", {})
    response = client.get(
        f"/api/runs/{rid}/events", headers={**headers, "Last-Event-ID": "1"}
    )
    frames = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [e["sequence"] for e in frames if "sequence" in e] == [2]
    assert "event: complete" in response.text


def test_worker_keeps_customer_context_across_runs(env, saver):
    from app.graph import build_graph
    from app.worker import process
    from app.runs import Runs
    from app.models import Conversation
    from app.db import sessions

    with sessions().begin() as s:
        c = Conversation(owner="alice")
        s.add(c)
        s.flush()
        cid = c.id
    graph = build_graph(Domain(env), saver)
    runs = Runs()
    request = Request(intent="policy", resource_ids=["hotel-0"])
    for _ in range(2):
        rid = runs.submit("alice", cid, request.model_dump(mode="json"))
        process(runs.claim(), graph, runs)
    from app.conversations import history

    context = history("alice", cid)
    assert len(context) == 2
    assert all(e["result"]["customer"]["answer"] for e in context)
    assert all(e["result"]["evidence"]["evidence"] for e in context)
