import json
from sqlalchemy import select, func
from app.db import sessions
from app.models import Run, Event, Conversation, Proposal, Operation, now


class Runs:
    def submit(self, owner, conversation, payload, text=""):
        with sessions().begin() as s:
            c = s.scalar(
                select(Conversation)
                .where(Conversation.id == conversation)
                .with_for_update()
            )
            if not c or c.owner != owner:
                raise ValueError("会话不存在")
            active = s.scalar(
                select(Run).where(
                    Run.conversation == conversation,
                    Run.status.in_(["QUEUED", "RUNNING", "WAITING"]),
                )
            )
            if active:
                raise ValueError("会话有进行中的任务；先处理审批")
            c.history = [
                *c.history,
                {"text": text or payload.get("question", ""), "request": payload},
            ]
            run = Run(owner=owner, conversation=conversation, payload=payload)
            s.add(run)
            s.flush()
            return run.id

    def get(self, owner, rid):
        with sessions()() as s:
            r = s.get(Run, rid)
            if not r or r.owner != owner:
                raise ValueError("运行不存在")
            return r

    def claim(self):
        with sessions().begin() as s:
            r = s.scalar(
                select(Run)
                .where(
                    (Run.status == "QUEUED")
                    | ((Run.status == "RUNNING") & (Run.lease_until < now()))
                )
                .order_by(Run.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not r:
                return None
            r.status = "RUNNING"
            r.lease_until = now() + 120
            r.fence += 1
            s.flush()
            return r

    def heartbeat(self, rid, fence):
        with sessions().begin() as s:
            r = s.scalar(select(Run).where(Run.id == rid).with_for_update())
            if r.fence != fence or r.status != "RUNNING":
                return False
            r.lease_until = now() + 120
            return True

    def event(self, rid, fence, kind, payload):
        with sessions().begin() as s:
            r = s.scalar(select(Run).where(Run.id == rid).with_for_update())
            if r.fence != fence or r.lease_until < now():
                raise ValueError("旧 worker 不能追加事件")
            seq = (
                s.scalar(select(func.max(Event.sequence)).where(Event.run == rid)) or 0
            ) + 1
            s.add(
                Event(
                    run=rid,
                    sequence=seq,
                    kind=kind,
                    payload=json.loads(json.dumps(payload, default=str)),
                )
            )

    def complete(self, rid, fence, status, result, error=""):
        with sessions().begin() as s:
            r = s.scalar(select(Run).where(Run.id == rid).with_for_update())
            if r.fence != fence:
                return
            r.status = status
            r.result = result
            r.error = error
            r.lease_until = 0

    def resume(self, owner, rid, decision):
        if decision.get("decision") not in ("approve", "reject"):
            raise ValueError("审批决定非法")
        with sessions().begin() as s:
            r = s.scalar(select(Run).where(Run.id == rid).with_for_update())
            if not r or r.owner != owner:
                raise ValueError("运行不存在")
            if r.status in ("QUEUED", "RUNNING", "DONE"):
                return {"status": r.status}
            if r.status != "WAITING":
                raise ValueError("运行没有待审批")
            proposal = r.result["approval"]["proposal"]
            if decision.get("version") != proposal["version"]:
                raise ValueError("审批版本不匹配")
            r.resume = decision
            r.status = "QUEUED"
            return {"status": "QUEUED"}

    def events(self, owner, rid, after=0):
        self.get(owner, rid)
        with sessions()() as s:
            return [
                {
                    "id": e.id,
                    "sequence": e.sequence,
                    "type": e.kind,
                    "payload": e.payload,
                }
                for e in s.scalars(
                    select(Event)
                    .where(Event.run == rid, Event.sequence > after)
                    .order_by(Event.sequence)
                )
            ]

    def cancel(self, owner, rid):
        with sessions().begin() as s:
            r = s.scalar(select(Run).where(Run.id == rid).with_for_update())
            if not r or r.owner != owner:
                raise ValueError("运行不存在")
            if r.status in ("DONE", "FAILED", "CANCELLED"):
                return {"status": r.status}
            r.cancel_requested = 1
            if r.status != "RUNNING":
                p = s.get(Proposal, r.id)
                if p and p.status == "PENDING":
                    p.status = "REJECTED"
                r.status = "CANCELLED"
            return {
                "status": r.status,
                "message": "停止尚未执行的操作；已完成订单不会自动取消",
            }

    def completed_operations(self, rid):
        with sessions()() as s:
            return [
                o.result
                for o in s.scalars(select(Operation).where(Operation.proposal == rid))
            ]
