"""验证框架边界及业务接缝，不以 Mock 的输出证明模型质量。"""

from types import SimpleNamespace
from datetime import date
from pathlib import Path
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.node_parser import get_leaf_nodes
from llama_index.core.schema import TextNode, NodeWithScore, QueryBundle
from llama_index.postprocessor.dashscope_rerank import DashScopeRerank
from app.agents import Agents, ScriptModel
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
        client=env.client, embed=MockEmbedding(embed_dim=32), collection=env.collection
    )
    after = restarted.retrieve(query)
    assert before.snapshot == after.snapshot
    assert {e.node_id for e in before.evidence} == {e.node_id for e in after.evidence}


def test_native_customer_memory_scoped_by_owner_and_conversation(env):
    saver = InMemorySaver()
    agents = Agents(Domain(env), saver)
    req = Request(intent="policy", resource_ids=["hotel-0"])
    agents.customer("alice", req, "same-conversation")
    agents.customer("alice", req, "same-conversation")
    state = saver.get_tuple(
        {"configurable": {"thread_id": "customer:alice:same-conversation"}}
    )
    assert (
        sum(m.type == "human" for m in state.checkpoint["channel_values"]["messages"])
        == 2
    )
    agents.customer("bob", req, "same-conversation")
    other = saver.get_tuple(
        {"configurable": {"thread_id": "customer:bob:same-conversation"}}
    )
    assert (
        sum(m.type == "human" for m in other.checkpoint["channel_values"]["messages"])
        == 1
    )


def test_native_summarization_runs_in_agent_loop():
    saver = InMemorySaver()
    agent = create_agent(
        ScriptModel(answer="收到"),
        tools=[],
        checkpointer=saver,
        middleware=[
            SummarizationMiddleware(
                model=FakeListChatModel(responses=["保留用户的出行约束"]),
                trigger=("messages", 6),
                keep=("messages", 2),
            )
        ],
    )
    cfg = {"configurable": {"thread_id": "summary-test"}}
    for i in range(5):
        result = agent.invoke({"messages": [("user", f"第{i}条需求")]}, cfg)
    assert any("保留用户的出行约束" in str(m.content) for m in result["messages"])
    assert len(result["messages"]) < 10


def test_native_reranker_sdk_boundary(monkeypatch):
    import dashscope

    def call(**kwargs):
        assert kwargs["query"] == "取消费" and kwargs["top_n"] == 1
        return SimpleNamespace(
            output=SimpleNamespace(
                results=[SimpleNamespace(index=1, relevance_score=0.9)]
            )
        )

    monkeypatch.setattr(dashscope.TextReRank, "call", call)
    nodes = [
        NodeWithScore(node=TextNode(id_="wrong", text="位置")),
        NodeWithScore(node=TextNode(id_="right", text="取消费")),
    ]
    result = DashScopeRerank(top_n=1, api_key="test-only").postprocess_nodes(
        nodes, query_bundle=QueryBundle("取消费")
    )
    assert result[0].node.node_id == "right" and result[0].score == 0.9


def test_insufficient_evidence_never_calls_llm(env, monkeypatch):
    def forbidden():
        raise AssertionError("没有适用证据时不应生成答案")

    monkeypatch.setattr("app.knowledge.rag_llm", forbidden)
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


def test_worker_keeps_customer_context_across_runs(env):
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
    graph = build_graph(Domain(env), InMemorySaver())
    runs = Runs()
    request = Request(intent="policy", resource_ids=["hotel-0"])
    for _ in range(2):
        rid = runs.submit("alice", cid, request.model_dump(mode="json"))
        process(runs.claim(), graph, runs)
    result = runs.get("alice", rid).result
    assert sum(m["role"] == "human" for m in result["customer"]["trace"]) == 2
