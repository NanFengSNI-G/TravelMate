import asyncio
from contextlib import asynccontextmanager
import base64
import copy
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from app.auth import token, decode, password_ok
from app.db import sessions
from app.models import (
    User,
    Conversation,
    Plan,
    Case,
    Revision,
    Resource,
    Run,
    Event,
    Quote,
    Order,
    now,
)
from app.contracts import Message, Request
from app.agents import classify
from app.runs import Runs
from app.domain import Domain
from app.activity import progress_steps, public_event
from app.config import settings


@asynccontextmanager
async def lifespan(app):
    settings().dashscope_api_key
    yield


app = FastAPI(title="TravelMate", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:15173", "http://127.0.0.1:15173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
runs = Runs()


@app.exception_handler(ValueError)
async def value_error(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": str(exc)})


def current(authorization: str = Header(default="")):
    try:
        uid = decode(authorization.removeprefix("Bearer "))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "请重新登录")
    with sessions()() as s:
        user = s.get(User, uid)
        if not user:
            raise HTTPException(401, "用户不存在")
        return user


def admin(user=Depends(current)):
    if user.role != "admin":
        raise HTTPException(403, "仅人工客服/管理员可操作")
    return user


class Login(BaseModel):
    name: str
    password: str


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": settings().model_name,
        "embedding": settings().embed_model,
        "rerank": settings().rerank_model,
    }


@app.post("/api/login")
def login(req: Login):
    with sessions()() as s:
        user = s.scalar(select(User).where(User.name == req.name))
        if not user or not password_ok(req.password, user.password):
            raise HTTPException(401, "用户名或密码错误")
        return {"token": token(user.id), "user": {"id": user.id, "role": user.role}}


@app.post("/api/conversations")
def conversation(user=Depends(current)):
    with sessions().begin() as s:
        row = Conversation(owner=user.id)
        s.add(row)
        s.flush()
        return {"id": row.id}


@app.post("/api/conversations/{cid}/messages")
def message(cid: str, req: Message, user=Depends(current)):
    with sessions()() as s:
        c = s.get(Conversation, cid)
        if not c or c.owner != user.id or c.deleted:
            raise ValueError("会话不存在")
        from app.conversations import history as conversation_history

        history = conversation_history(user.id, cid)
    request = req.request or classify(req.text, history)
    if req.request and req.request.option_id:
        from app.conversations import select_option

        request = select_option(req.request, history)
    request = request.model_copy(update={"question": req.text})
    if request.intent == "admin_write" or request.admin_action is not None:
        raise HTTPException(403, "后台变更必须通过专用管理员入口")
    return {
        "run_id": runs.submit(user.id, cid, request.model_dump(mode="json"), req.text)
    }


@app.get("/api/runs/{rid}")
def run(rid: str, user=Depends(current)):
    r = runs.get(user.id, rid)
    return run_view(r)


class Decision(BaseModel):
    decision: str
    version: int


@app.post("/api/runs/{rid}/approval")
def approval(rid: str, req: Decision, user=Depends(current)):
    if req.decision not in ("approve", "reject"):
        raise ValueError("仅允许确认或拒绝；修改需拒绝后提交新请求")
    return runs.resume(user.id, rid, req.model_dump())


@app.get("/api/runs/{rid}/events", response_class=EventSourceResponse)
async def events(
    rid: str,
    after: int = 0,
    last_event_id: int = Header(default=0, ge=0),
    user=Depends(current),
):
    await asyncio.to_thread(runs.get, user.id, rid)
    cursor = max(after, last_event_id)
    for _ in range(600):
        batch = await asyncio.to_thread(runs.events, user.id, rid, cursor)
        for event in batch:
            cursor = event["sequence"]
            yield ServerSentEvent(id=str(cursor), data=public_event(event))
        state = await asyncio.to_thread(runs.get, user.id, rid)
        if state.status in ("DONE", "FAILED", "WAITING", "CANCELLED"):
            yield ServerSentEvent(event="complete", data={})
            return
        await asyncio.sleep(1)


@app.get("/api/resources")
def resources(user=Depends(current)):
    with sessions()() as s:
        return [
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind,
                "price": r.price,
                "supplier": r.supplier,
                "product": r.product,
                "details": r.details,
            }
            for r in s.scalars(select(Resource))
        ]


@app.get("/api/orders")
def orders(user=Depends(current)):
    return Domain(None).orders(user.id)


@app.get("/api/plans/{pid}")
def plan(pid: str, user=Depends(current)):
    with sessions()() as s:
        p = s.get(Plan, pid)
        if not p or p.owner != user.id:
            raise HTTPException(404, "方案不存在")
        return {"id": p.id, "options": p.options}


def queue_admin(user, action):
    with sessions().begin() as s:
        c = Conversation(owner=user.id)
        s.add(c)
        s.flush()
        cid = c.id
    labels = {
        "case_claim": "领取服务申请",
        "case_reply": "回复服务申请",
        "knowledge_import": "导入知识文档",
        "knowledge_publish": "发布知识版本",
        "knowledge_revoke": "撤回知识版本",
        "knowledge_rollback": "恢复知识版本",
    }
    question = labels.get(action["kind"], "核对管理操作")
    payload = Request(
        intent="admin_write", question=question, admin_action=action
    ).model_dump(mode="json")
    return {"run_id": runs.submit(user.id, cid, payload, question)}


class ImportDocument(BaseModel):
    name: str = Field(min_length=1, max_length=180)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if (
            "/" in value
            or "\\" in value
            or any(ord(char) < 32 for char in value)
            or len(value.encode("utf-8")) > 240
            or Path(value).suffix.lower() not in (".md", ".pdf")
        ):
            raise ValueError(
                "请上传文件名有效的 Markdown 或 PDF 文件，文件名不能包含路径"
            )
        return Path(value).stem + Path(value).suffix.lower()

    content_base64: str = Field(max_length=7000000)
    metadata: dict


@app.post("/api/knowledge/import")
def import_document(req: ImportDocument, user=Depends(admin)):
    content = base64.b64decode(req.content_base64, validate=True)
    if len(content) > 5000000:
        raise ValueError("最大 5MB")
    from app.contracts import PolicyMetadata

    PolicyMetadata.model_validate(req.metadata)
    return queue_admin(user, {"kind": "knowledge_import", **req.model_dump()})


@app.get("/api/knowledge/revisions")
def revisions(user=Depends(admin)):
    with sessions()() as s:
        return [
            {
                "id": r.id,
                "document": r.document,
                "product": r.product,
                "supplier": r.supplier,
                "source": r.source,
                "rules": r.rules,
                "status": r.status,
                "valid_from": r.valid_from,
                "valid_to": r.valid_to,
                "error": r.error,
            }
            for r in s.scalars(select(Revision))
        ]


@app.post("/api/knowledge/{rid}/publish")
def publish(rid: str, user=Depends(admin)):
    return queue_admin(user, {"kind": "knowledge_publish", "revision": rid})


@app.post("/api/knowledge/{rid}/revoke")
def revoke(rid: str, user=Depends(admin)):
    return queue_admin(user, {"kind": "knowledge_revoke", "revision": rid})


@app.get("/api/cases")
def cases(user=Depends(current)):
    with sessions()() as s:
        stmt = (
            select(Case)
            if user.role == "admin"
            else select(Case).where(Case.owner == user.id)
        )
        return [
            {
                "id": c.id,
                "customer": (
                    s.get(User, c.owner).name if s.get(User, c.owner) else "旅客"
                ),
                "context": c.context,
                "status": c.status,
                "assigned": c.assigned,
                "replies": c.replies,
            }
            for c in s.scalars(stmt)
        ]


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    close: bool = False


@app.post("/api/cases/{cid}/claim")
def claim_case(cid: str, user=Depends(admin)):
    return queue_admin(user, {"kind": "case_claim", "case_id": cid})


@app.post("/api/cases/{cid}/reply")
def reply(cid: str, req: Reply, user=Depends(admin)):
    return queue_admin(user, {"kind": "case_reply", "case_id": cid, **req.model_dump()})


@app.post("/api/cases/{cid}/messages")
def case_message(cid: str, req: Reply, user=Depends(current)):
    case = Domain(None).support_case(user.id, cid)
    if case.status == "CLOSED" or req.close:
        raise ValueError("已结束的申请不能补充，请新建服务申请")
    with sessions().begin() as s:
        conversation = Conversation(owner=user.id)
        s.add(conversation)
        s.flush()
        conversation_id = conversation.id
    request = Request(intent="support", question=req.text, case_id=cid)
    return {
        "run_id": runs.submit(
            user.id, conversation_id, request.model_dump(mode="json"), req.text
        )
    }


@app.post("/api/runs/{rid}/cancel")
def cancel_run(rid: str, user=Depends(current)):
    return runs.cancel(user.id, rid)


@app.post("/api/runs/{rid}/retry")
def retry_run(rid: str, user=Depends(current)):
    original = runs.get(user.id, rid)
    if original.payload.get("intent") == "admin_write" and user.role != "admin":
        raise HTTPException(403, "仅管理员可重新发起管理操作")
    if original.status not in ("WAITING", "FAILED", "CANCELLED"):
        raise ValueError("只能重新获取待确认、失败或停止的需求")
    if original.status == "WAITING":
        runs.cancel(user.id, rid)
    return {
        "run_id": runs.submit(
            user.id,
            original.conversation,
            original.payload,
            original.payload.get("question", "重新获取方案"),
        )
    }


@app.post("/api/knowledge/{rid}/rollback")
def rollback(rid: str, user=Depends(admin)):
    return queue_admin(user, {"kind": "knowledge_rollback", "revision": rid})


def public_content(value):
    if isinstance(value, dict):
        return {
            key: public_content(item)
            for key, item in value.items()
            if key not in ("trace", "content_base64")
        }
    if isinstance(value, list):
        return [public_content(item) for item in value]
    return value


def run_view(row):
    result = public_content(copy.deepcopy(row.result))
    view = {
        "id": row.id,
        "conversation_id": row.conversation,
        "status": row.status,
        "cancel_requested": row.cancel_requested,
        "payload": public_content(row.payload),
        "result": result,
        "error": row.error,
        "preview": [],
    }
    with sessions()() as s:
        events = s.scalars(
            select(Event)
            .where(Event.run == row.id, Event.kind == "progress")
            .order_by(Event.sequence)
        )
        view["activity"] = [
            step
            for event in events
            for step in progress_steps(event.payload, event.sequence)
        ]
    proposal = result.get("approval", {}).get("proposal")
    if proposal:
        with sessions()() as s:
            for action in proposal["actions"]:
                preview = {"kind": action["kind"], "valid": True}
                if action["kind"] in ("book", "change", "cancel"):
                    quote = (
                        s.get(Quote, action.get("quote"))
                        if action.get("quote")
                        else None
                    )
                    order = (
                        s.get(Order, action.get("order"))
                        if action.get("order")
                        else None
                    )
                    if (quote and quote.owner != row.owner) or (
                        order and order.owner != row.owner
                    ):
                        raise ValueError("审批内容不属于当前用户")
                    rid = quote.resource if quote else order.resource if order else None
                    resource = s.get(Resource, rid) if rid else None
                    preview.update(
                        {
                            "name": resource.name if resource else "资源暂不可用",
                            "resource_kind": resource.kind if resource else None,
                            "resource_id": rid,
                            "amount": (
                                quote.amount if quote else order.amount if order else 0
                            ),
                            "quantity": (
                                quote.quantity
                                if quote
                                else order.quantity if order else 0
                            ),
                            "slots": (
                                quote.slots if quote else order.slots if order else []
                            ),
                            "details": resource.details if resource else {},
                            "fee": action.get("fee"),
                            "difference": (
                                quote.amount - order.amount if quote and order else None
                            ),
                            "valid": bool(resource)
                            and (action["kind"] == "cancel" or quote is not None)
                            and (
                                not quote
                                or (
                                    quote.expires >= now()
                                    and quote.resource_version == resource.version
                                )
                            )
                            and (
                                not order
                                or order.version == action.get("order_version")
                            ),
                        }
                    )
                else:
                    data = action.get("data", {})
                    preview["data"] = data
                    if action["kind"] == "admin_write":
                        if data.get("case_id"):
                            case = s.get(Case, data["case_id"])
                            preview["subject"] = (
                                case.context.get("request", {}).get(
                                    "question", "服务申请"
                                )
                                if case
                                else "申请已不可用"
                            )
                        elif data.get("revision"):
                            revision = s.get(Revision, data["revision"])
                            preview["subject"] = (
                                f"{revision.document} · {revision.supplier} / {revision.product} · {revision.valid_from} 至 {revision.valid_to}"
                                if revision
                                else "版本已不可用"
                            )
                view["preview"].append(preview)
    return view


@app.get("/api/me")
def me(user=Depends(current)):
    return {"id": user.id, "name": user.name, "role": user.role}


@app.get("/api/conversations")
def conversations(user=Depends(current)):
    with sessions()() as s:
        rows = list(
            s.scalars(
                select(Conversation).where(
                    Conversation.owner == user.id, Conversation.deleted == 0
                )
            )
        )
        return sorted(
            [
                {
                    "id": row.id,
                    "title": row.title
                    or next(
                        (
                            entry.get("text", "")
                            for entry in row.history
                            if entry.get("text")
                        ),
                        "新的旅行对话",
                    )[:64],
                    "preview": (
                        row.history[-1].get("text", "")[:100] if row.history else ""
                    ),
                    "message_count": len(row.history),
                    "updated_at": max(
                        (entry.get("created_at", 0) for entry in row.history),
                        default=row.created_at,
                    ),
                }
                for row in rows
            ],
            key=lambda item: item["updated_at"],
            reverse=True,
        )


class ConversationTitle(BaseModel):
    title: str = Field(min_length=1, max_length=64)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


@app.patch("/api/conversations/{cid}")
def rename_conversation(cid: str, req: ConversationTitle, user=Depends(current)):
    with sessions().begin() as s:
        row = s.scalar(
            select(Conversation).where(Conversation.id == cid).with_for_update()
        )
        if not row or row.owner != user.id or row.deleted:
            raise HTTPException(404, "对话不存在")
        row.title = req.title
        return {"id": row.id, "title": row.title}


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, user=Depends(current)):
    with sessions().begin() as s:
        row = s.scalar(
            select(Conversation).where(Conversation.id == cid).with_for_update()
        )
        if not row or row.owner != user.id or row.deleted:
            raise HTTPException(404, "对话不存在")
        pending = s.scalar(
            select(Run.id)
            .where(
                Run.conversation == cid,
                Run.status.in_(["QUEUED", "RUNNING", "WAITING"]),
            )
            .limit(1)
        )
        if pending:
            raise HTTPException(
                409, "会话还有正在处理或待确认的操作，请先打开会话停止任务，再删除。"
            )
        row.deleted = 1
        row.context_version += 1
    from app.cache import clear_conversation

    clear_conversation(user.id, cid)
    return {"id": cid, "deleted": True}


@app.get("/api/conversations/{cid}")
def conversation_detail(cid: str, user=Depends(current)):
    with sessions()() as s:
        row = s.get(Conversation, cid)
        if not row or row.owner != user.id or row.deleted:
            raise HTTPException(404, "对话不存在")
        runs_for_chat = list(
            s.scalars(select(Run).where(Run.conversation == cid, Run.owner == user.id))
        )
        by_id = {run.id: run for run in runs_for_chat}
        entries = []
        for entry in row.history:
            linked = by_id.get(entry.get("run_id"))
            if not linked:
                matches = [
                    run for run in runs_for_chat if run.payload == entry.get("request")
                ]
                linked = matches[0] if len(matches) == 1 else None
            entries.append(
                {
                    "text": entry.get("text", ""),
                    "created_at": entry.get("created_at"),
                    "run": run_view(linked) if linked else None,
                }
            )
        return {"id": row.id, "messages": entries}


@app.get("/api/runs")
def run_list(user=Depends(current)):
    with sessions()() as s:
        rows = list(
            s.scalars(
                select(Run).where(
                    Run.owner == user.id,
                    Run.conversation.in_(
                        select(Conversation.id).where(
                            Conversation.owner == user.id,
                            Conversation.deleted == 0,
                        )
                    ),
                )
            )
        )
        histories = s.scalars(
            select(Conversation).where(
                Conversation.owner == user.id, Conversation.deleted == 0
            )
        )
        dates = {
            entry["run_id"]: entry.get("created_at", 0)
            for chat in histories
            for entry in chat.history
            if entry.get("run_id")
        }
        rows.sort(key=lambda row: dates.get(row.id, 0), reverse=True)
        visible = [
            row for row in rows if row.status in ("QUEUED", "RUNNING", "WAITING")
        ]
        visible += [
            row for row in rows if row.status not in ("QUEUED", "RUNNING", "WAITING")
        ][:100]
        return [{**run_view(row), "created_at": dates.get(row.id)} for row in visible]


@app.get("/api/plans")
def plans(user=Depends(current)):
    with sessions()() as s:
        return [
            {"id": row.id, "options": row.options, "created": row.created}
            for row in s.scalars(
                select(Plan).where(Plan.owner == user.id).order_by(Plan.created.desc())
            )
        ]
