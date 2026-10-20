import json
import pytest
from app.activity import progress_steps, public_event
from app.contracts import Request


def test_activity_reports_only_current_turn_tool_names():
    payload = {
        "customer": {
            "customer": {
                "trace": [
                    {"role": "human", "content": "旧问题"},
                    {
                        "role": "ai",
                        "content": "不公开的内部文本",
                        "calls": [{"name": "retrieve_policy"}],
                    },
                    {"role": "human", "content": "现在查询订单"},
                    {
                        "role": "ai",
                        "calls": [
                            {"name": "get_my_orders", "args": {"secret": "private"}}
                        ],
                    },
                ]
            }
        }
    }
    step = progress_steps(payload, 3)[0]
    assert step["tools"] == [{"label": "读取本人订单", "count": 1}]
    assert "private" not in json.dumps(step) and "content" not in step


def test_public_events_do_not_export_raw_graph_state():
    event = {
        "sequence": 4,
        "type": "progress",
        "payload": {
            "planning": {
                "results": {"hotel": {"tool_calls": 2, "candidates": [{"private": 1}]}}
            },
            "__interrupt__": {"secret": "hidden"},
        },
    }
    result = public_event(event)
    assert list(result["payload"]) == ["planning"]
    assert result["payload"]["planning"]["tools"][0]["count"] == 2
    assert "private" not in json.dumps(result) and "hidden" not in json.dumps(result)
    assert (
        public_event(
            {"sequence": 5, "type": "result", "payload": {"trace": "private"}}
        )["payload"]
        == {}
    )
    assert progress_steps(None, 1) == []


def test_daily_chat_is_a_supported_intent_and_duplicate_ids_are_invalid():
    assert Request(intent="chat", question="你好").question == "你好"
    with pytest.raises(ValueError, match="重复选择"):
        Request(intent="book", resource_ids=["hotel-0", "hotel-0"])
