from datetime import date
import pytest
from app.agents import classify, Agents
from app.contracts import Request, TurnUnderstanding
from app.domain import Domain


def test_language_output_has_no_business_defaults():
    turn = TurnUnderstanding(intent="chat", resolved_question="打个招呼")
    assert turn.parameters.model_dump(exclude_none=True) == {}
    assert "北京" not in turn.model_dump_json()
    assert "600000" not in turn.model_dump_json()


MENU = [
    {
        "text": "你能做什么？",
        "result": {
            "customer": {"answer": "1. 查看已保存行程\n2. 查看本人订单\n3. 政策咨询"}
        },
    }
]
SEARCH = [
    {
        "text": "2030年10月1日至3日，一个人从北京去上海，帮我查航班和酒店。",
        "request": {
            "intent": "search",
            "departure": "北京",
            "destination": "上海",
            "start": "2030-10-01",
            "end": "2030-10-03",
            "people": 1,
        },
        "result": {"customer": {"answer": "已了解您的查询需求。"}},
    }
]


@pytest.mark.live
@pytest.mark.parametrize(
    "text,history,intent,expected",
    [
        ("第二个", MENU, "orders", {}),
        ("就查订单那个", MENU, "orders", {}),
        ("第七个", MENU, "chat", {}),
        ("4", [], "chat", {}),
        (
            "4",
            [
                {
                    "text": "我要查酒店",
                    "request": {"intent": "search", "resource_kinds": ["hotel"]},
                    "result": {"customer": {"answer": "几位入住？"}},
                }
            ],
            "search",
            {"people": 4},
        ),
        (
            "改成两个人",
            SEARCH,
            "search",
            {
                "people": 2,
                "destination": "上海",
                "start": date(2030, 10, 1),
                "end": date(2030, 10, 3),
            },
        ),
        ("不是上海，是杭州", SEARCH, "search", {"destination": "杭州", "people": 1}),
        (
            "先不订了，看看我已经有的订单",
            [
                {
                    "text": "我想预订酒店",
                    "result": {"customer": {"answer": "需要先核对报价再确认。"}},
                }
            ],
            "orders",
            {},
        ),
        (
            "你好",
            [
                {
                    "text": "我要找人工",
                    "request": {"intent": "support"},
                    "result": {"customer": {"answer": "请核对人工服务申请。"}},
                }
            ],
            "chat",
            {},
        ),
    ],
)
def test_followup_understanding(text, history, intent, expected):
    request = classify(text, history)
    assert request.intent == intent
    assert request.question == text
    for field, value in expected.items():
        assert getattr(request, field) == value


@pytest.mark.live
def test_greeting_does_not_claim_default_trip(db_env):
    result = Agents(Domain(None)).customer(
        "alice", Request(intent="chat", question="你好，我叫小林")
    )
    answer = result["answer"]
    assert "北京" not in answer and "上海" not in answer and "6000" not in answer
    assert not any(m["calls"] for m in result["trace"])


@pytest.mark.live
def test_quote_explanation_does_not_prepare_another_write():
    request = classify(
        "先不确认，这个变更要补多少钱？",
        [
            {
                "text": "把航班改到第二天",
                "request": {"intent": "change"},
                "result": {
                    "approval": {
                        "proposal": {"actions": [{"kind": "change", "quote": "q1"}]}
                    }
                },
            }
        ],
    )
    assert request.intent == "chat"


@pytest.mark.live
def test_relative_dates_use_current_business_date():
    from datetime import timedelta

    request = classify("明天出发后天回来，从北京去上海，一个人，查航班酒店")
    assert request.start == date.today() + timedelta(days=1)
    assert request.end == date.today() + timedelta(days=2)
