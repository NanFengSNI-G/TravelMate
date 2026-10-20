from sqlalchemy import select
from app.db import sessions
from app.models import Conversation, Run
from app.cache import snapshot_key, read_snapshot, write_snapshot


def visible(value):
    if isinstance(value, dict):
        return {
            k: visible(v)
            for k, v in value.items()
            if k not in ("trace", "content_base64", "admin_action")
        }
    if isinstance(value, list):
        return [visible(v) for v in value]
    return value


def prompt_request(request):
    request = visible(request)
    intent = request.get("intent")
    if intent == "chat":
        return {}
    allowed = {
        "orders": {"intent", "resolved_question"},
        "plans": {"intent", "resolved_question"},
        "support": {"intent", "resolved_question"},
        "policy": {
            "intent",
            "resolved_question",
            "resource_ids",
            "order_id",
            "start",
            "end",
        },
    }.get(intent)
    return {
        k: v
        for k, v in request.items()
        if v is not None and (allowed is None or k in allowed)
    }


def history(owner, conversation, before_run=None):
    with sessions()() as s:
        version = s.scalar(
            select(Conversation.context_version).where(
                Conversation.id == conversation,
                Conversation.owner == owner,
                Conversation.deleted == 0,
            )
        )
        if version is None:
            raise ValueError("会话不存在")
        key = snapshot_key(owner, conversation, version, before_run)
        cached = read_snapshot(key)
        if cached is not None:
            return cached
        entries = s.get(Conversation, conversation).history
        if before_run:
            entries = entries[
                : next(
                    (i for i, e in enumerate(entries) if e.get("run_id") == before_run),
                    len(entries),
                )
            ]
        entries = entries[-20:]
        ids = [e["run_id"] for e in entries if e.get("run_id")]
        runs = (
            {
                r.id: r
                for r in s.scalars(
                    select(Run).where(Run.id.in_(ids), Run.owner == owner)
                )
            }
            if ids
            else {}
        )
        result = []
        for entry in entries:
            r = runs.get(entry.get("run_id"))
            item = {
                "text": entry.get("text", ""),
                "request": visible(entry.get("request", {})),
            }
            if r:
                item.update(run_id=r.id, status=r.status, result=visible(r.result))
            result.append(item)
        write_snapshot(key, result)
        return result


def options_from_history(entries):
    for entry in reversed(entries):
        result = entry.get("result", {})
        options = result.get("plan", {}).get("options") or result.get("repair", {}).get(
            "options"
        )
        if not options:
            for action in (
                result.get("approval", {}).get("proposal", {}).get("actions", [])
            ):
                if action.get("kind") == "plan_create":
                    options = action["data"].get("options")
                elif action.get("kind") == "repair_save":
                    options = action["data"].get("report", {}).get("options")
        if options:
            return [
                {**o, "option_id": o.get("option_id", f'{entry["run_id"]}:{i + 1}')}
                for i, o in enumerate(options)
            ]
    return []


def select_option(request, entries, index=None):
    options = options_from_history(entries)
    option = None
    if request.option_id:
        option = next(
            (
                o
                for entry in reversed(entries)
                for o in options_from_history([entry])
                if o["option_id"] == request.option_id
            ),
            None,
        )
    elif index is not None:
        option = options[index - 1] if 1 <= index <= len(options) else None
    else:
        return request
    if option is None:
        raise ValueError("该方案不在当前会话中，请重新选择展示的方案")
    data = request.model_dump()
    data.update(
        option_id=option["option_id"],
        resource_ids=option["resource_ids"],
        start=request.start or option["start"],
        end=request.end or option["end"],
    )
    return type(request).model_validate(data)


def assistant_content(result):
    import json

    result = visible(result)
    answer = result.get("customer", {}).get("answer") or result.get("message", "")
    facts = {k: v for k, v in result.items() if k != "customer"}
    content = str(answer)
    if facts:
        content += "\n本轮服务端业务结果：" + json.dumps(facts, ensure_ascii=False)
    return content


def messages(entries, current=None, current_id=None):
    import json
    from langchain_core.messages import HumanMessage, AIMessage, trim_messages
    from langchain_core.messages.utils import count_tokens_approximately
    from app.config import settings

    turns = []
    for index, entry in enumerate(entries or []):
        rid = entry.get("run_id", f"history-{index}")
        text = entry.get("text") or entry.get("request", {}).get("question", "")
        if not text:
            continue
        turns.append(HumanMessage(content=text, id=f"{rid}:user"))
        content = assistant_content(entry.get("result", {}))
        parameters = prompt_request(entry.get("request", {}))
        if parameters:
            content += "\n该历史轮次的业务参数：" + json.dumps(
                parameters, ensure_ascii=False
            )
        if not content:
            content = "本轮尚无最终结果，状态：" + entry.get("status", "UNKNOWN")
        turns.append(AIMessage(content=content, id=f"{rid}:assistant"))
    if current is not None:
        turns.append(
            HumanMessage(
                content=current, id=f"{current_id}:user" if current_id else None
            )
        )
    return trim_messages(
        turns,
        max_tokens=settings().context_max_tokens,
        token_counter=count_tokens_approximately,
        strategy="last",
        start_on="human",
    )
