"""框架计算检索指标；业务标签仍由人按原文维护。"""

import json
import statistics
import time
from datetime import date
from pathlib import Path
from sqlalchemy import select
from llama_index.core.evaluation import RetrieverEvaluator
from app.knowledge import Knowledge
from app.contracts import Query
from app.db import sessions
from app.models import Node


def evaluate(k=None, output=Path("artifacts/retrieval-results.json")):
    k = k or Knowledge()
    questions = json.loads(Path("evals/questions.json").read_text())
    rows, summary = [], []
    for mode, parent in [
        ("default", False),
        ("sparse", False),
        ("hybrid", False),
        ("hybrid", True),
    ]:
        group = []
        for item in questions:
            query = Query(
                question=item["question"],
                supplier=item["supplier"],
                product=item["product"],
                applicable_date=date.today(),
            )
            start = time.perf_counter()
            expected = item["expected_section"]
            if expected:
                revision = k.revisions(query)[0]
                with sessions()() as s:
                    expected_ids = list(
                        s.scalars(
                            select(Node.id).where(
                                Node.revision == revision.id, Node.section == expected
                            )
                        )
                    )
                if not expected_ids:
                    raise ValueError("标签无法映射到当前知识节点：" + expected)
                evaluator = RetrieverEvaluator.from_metric_names(
                    ["mrr", "hit_rate", "recall"],
                    retriever=k.retriever(query, mode, parent, top_k=5),
                )
                result = evaluator.evaluate(query.question, expected_ids=expected_ids)
                row = {
                    "metrics": result.metric_vals_dict,
                    "node_ids": result.retrieved_ids,
                }
            else:
                evidence = k.retrieve(query, mode, parent, rerank=False)
                row = {
                    "out_of_scope_rejected": evidence.status == "INSUFFICIENT",
                    "node_ids": [],
                }
            row.update(
                id=item["id"],
                mode=mode,
                parent=parent,
                seconds=time.perf_counter() - start,
            )
            group.append(row)
        positives = [r for r in group if "metrics" in r]
        negatives = [r for r in group if "out_of_scope_rejected" in r]
        times = sorted(r["seconds"] for r in group)
        summary.append(
            {
                "mode": mode,
                "parent": parent,
                "hit_rate_at_5": statistics.mean(
                    r["metrics"]["hit_rate"] for r in positives
                ),
                "mrr_at_5": statistics.mean(r["metrics"]["mrr"] for r in positives),
                "node_recall_at_5": statistics.mean(
                    r["metrics"]["recall"] for r in positives
                ),
                "out_of_scope_rejection": statistics.mean(
                    r["out_of_scope_rejected"] for r in negatives
                ),
                "p50_seconds": statistics.median(times),
                "p95_seconds": times[int(0.95 * (len(times) - 1))],
            }
        )
        rows.extend(group)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "summary": summary,
        "rows": rows,
        "scope": "60条合成查询；原生指标；相关section映射到其父/叶节点集合；MockEmbedding不代表语义模型质量；未评价回答忠实度",
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    evaluate()
