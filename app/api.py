import asyncio
import base64
import json
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.auth import token, decode, password_ok
from app.db import sessions
from app.models import User, Conversation, Plan, Case, Revision, Resource
from app.contracts import Message, Request
from app.agents import classify
from app.runs import Runs
from app.domain import Domain
from app.knowledge import Knowledge
from app.config import settings

app = FastAPI(title="TravelMate 教学实现")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:15173", "http://127.0.0.1:15173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
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
        "model_mode": settings().model_mode,
        "embed_mode": settings().embed_mode,
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
        if not c or c.owner != user.id:
            raise ValueError("会话不存在")
        history = c.history
    request = req.request or classify(req.text, history)
    if request.intent == "admin_write" or request.admin_action is not None:
        raise HTTPException(403, "后台变更必须通过专用管理员入口")
    return {
        "run_id": runs.submit(user.id, cid, request.model_dump(mode="json"), req.text)
    }


@app.get("/api/runs/{rid}")
def run(rid: str, user=Depends(current)):
    r = runs.get(user.id, rid)
    return {"id": r.id, "status": r.status, "result": r.result, "error": r.error}


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
            yield ServerSentEvent(id=str(cursor), data=event)
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
    """点击管理按钮只提交变更请求；正式写入仍须同一登录管理员确认。"""
    with sessions().begin() as s:
        c = Conversation(owner=user.id)
        s.add(c)
        s.flush()
        cid = c.id
    payload = Request(intent="admin_write", admin_action=action).model_dump(mode="json")
    return {"run_id": runs.submit(user.id, cid, payload)}


class ImportDocument(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.(md|pdf)$")
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


@app.post("/api/runs/{rid}/cancel")
def cancel_run(rid: str, user=Depends(current)):
    return runs.cancel(user.id, rid)


@app.post("/api/knowledge/{rid}/rollback")
def rollback(rid: str, user=Depends(admin)):
    return queue_admin(user, {"kind": "knowledge_rollback", "revision": rid})
