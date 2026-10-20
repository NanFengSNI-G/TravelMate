import math
import json
import base64
import hashlib
from app.config import settings
from datetime import date, timedelta
from sqlalchemy import select, func
from app.db import sessions
from app.models import (
    User,
    Resource,
    Inventory,
    Order,
    Quote,
    Proposal,
    Operation,
    Revision,
    Plan,
    Case,
    Run,
    now,
)
from app.contracts import Query


class Domain:
    def __init__(self, knowledge):
        self.knowledge = knowledge

    def orders(self, owner):
        with sessions()() as s:
            return [
                {
                    "id": o.id,
                    "resource": o.resource,
                    "status": o.status,
                    "amount": o.amount,
                    "quantity": o.quantity,
                    "version": o.version,
                    "slots": o.slots,
                }
                for o in s.scalars(select(Order).where(Order.owner == owner))
            ]

    def order(self, owner, oid):
        with sessions()() as s:
            row = s.get(Order, oid)
            if not row or row.owner != owner:
                raise ValueError("订单不存在")
            return row

    def pending_quotes(self, owner):
        result = []
        with sessions()() as s:
            for proposal in s.scalars(
                select(Proposal).where(
                    Proposal.owner == owner, Proposal.status == "PENDING"
                )
            ):
                actions = []
                for action in proposal.actions:
                    quote = (
                        s.get(Quote, action["quote"]) if action.get("quote") else None
                    )
                    order = (
                        s.get(Order, action["order"]) if action.get("order") else None
                    )
                    if (quote and quote.owner != owner) or (
                        order and order.owner != owner
                    ):
                        raise ValueError("报价不属于当前用户")
                    rid = quote.resource if quote else order.resource if order else None
                    resource = s.get(Resource, rid) if rid else None
                    if resource:
                        actions.append(
                            {
                                "kind": action["kind"],
                                "name": resource.name,
                                "amount_cents": quote.amount if quote else order.amount,
                                "difference_cents": (
                                    quote.amount - order.amount
                                    if quote and order
                                    else None
                                ),
                                "cancel_fee_cents": action.get("fee"),
                                "quantity": quote.quantity if quote else order.quantity,
                            }
                        )
                if actions:
                    result.append(
                        {
                            "proposal_id": proposal.id,
                            "expires": proposal.expires,
                            "expired": proposal.expires < now(),
                            "actions": actions,
                        }
                    )
        return result

    def policy_choices(self):
        with sessions()() as s:
            representatives = select(func.min(Resource.id)).group_by(
                Resource.kind, Resource.supplier, Resource.product
            )
            return [
                {"id": r.id, "name": f"{r.supplier} · {r.product}", "kind": r.kind}
                for r in s.scalars(
                    select(Resource).where(Resource.id.in_(representatives))
                )
            ]

    def catalog_summary(self):
        from app.demo_data import business_today

        with sessions()() as s:
            cities = sorted(
                set(
                    s.scalars(
                        select(Resource.details["destination"].as_string()).distinct()
                    )
                )
            )
            dates = s.execute(
                select(
                    func.min(Resource.details["date"].as_string()),
                    func.max(Resource.details["date"].as_string()),
                ).where(
                    Resource.kind == "flight",
                    Resource.details["date"].as_string() >= str(business_today()),
                )
            ).one()
            counts = dict(
                s.execute(
                    select(Resource.kind, func.count()).group_by(Resource.kind)
                ).all()
            )
            return {
                "cities": cities,
                "flight_dates": {"start": dates[0], "end": dates[1]},
                "resource_counts": {
                    "dated_flights": counts.get("flight", 0),
                    "hotel_room_types": counts.get("hotel", 0),
                },
                "scope": "本地合成演示目录，支持单程航班和酒店，不是真实供应商的实时库存",
            }

    def support_case(self, owner, case_id):
        with sessions()() as s:
            case = s.get(Case, case_id)
            if not case or case.owner != owner:
                raise ValueError("服务申请不存在")
            return case

    def search(self, kind, req):
        with sessions()() as s:
            query = select(Resource).where(
                Resource.kind == kind,
                Resource.details["destination"].as_string() == req.destination,
            )
            if kind == "flight":
                query = query.where(
                    Resource.details["departure"].as_string() == req.departure,
                    Resource.details["date"].as_string() == str(req.start),
                )
            rows = list(s.scalars(query.order_by(Resource.price, Resource.id)))
            slots_by_id = {r.id: self.slots(r, req) for r in rows}
            all_slots = [slot for slots in slots_by_id.values() for slot in slots]
            stock = (
                {
                    v.id: v.available
                    for v in s.scalars(
                        select(Inventory).where(Inventory.id.in_(all_slots))
                    )
                }
                if all_slots
                else {}
            )
            result = []
            for r in rows:
                slots = slots_by_id[r.id]
                quantity = (
                    req.people
                    if kind == "flight"
                    else math.ceil(req.people / r.details["max_people"])
                )
                if any(stock.get(slot, 0) < quantity for slot in slots):
                    continue
                result.append(
                    {
                        "id": r.id,
                        "name": r.name,
                        "kind": kind,
                        "supplier": r.supplier,
                        "product": r.product,
                        "amount": r.price
                        * quantity
                        * (len(slots) if kind == "hotel" else 1),
                        "slots": slots,
                        "quantity": quantity,
                    }
                )
            return result

    def slots(self, r, req):
        if not req.start or not req.end:
            raise ValueError("请提供入住和退房日期")
        if r.kind == "flight":
            if r.details["date"] != str(req.start):
                raise ValueError("航班日期不匹配")
            return [r.id]
        return [
            f"{r.id}-{req.start+timedelta(days=i)}"
            for i in range((req.end - req.start).days)
        ]

    def plans(self, owner):
        with sessions()() as s:
            return [
                {"id": p.id, "options": p.options, "created": p.created}
                for p in s.scalars(select(Plan).where(Plan.owner == owner))
            ]

    def evidence(self, owner, req):
        if req.order_id:
            order = self.order(owner, req.order_id)
            with sessions()() as s:
                r = s.get(Resource, order.resource)
            query = Query(
                question=req.resolved_question or req.question,
                supplier=r.supplier,
                product=r.product,
                applicable_date=date.today(),
                revision_id=order.revision,
            )
        else:
            if len(req.resource_ids) != 1:
                raise ValueError("请指定一个资源或本人订单后查询适用政策")
            with sessions()() as s:
                r = s.get(Resource, req.resource_ids[0])
                if not r:
                    raise ValueError("资源不存在")
            query = Query(
                question=req.resolved_question or req.question,
                supplier=r.supplier,
                product=r.product,
                applicable_date=date.today(),
            )
        return self.knowledge.retrieve(query)

    @staticmethod
    def ensure_not_booked(s, owner, resource, slots, exclude_order=None):
        rows = s.scalars(
            select(Order).where(
                Order.owner == owner,
                Order.resource == resource.id,
                Order.status == "CONFIRMED",
            )
        )
        requested = set(slots)
        if any(
            row.id != exclude_order and requested.intersection(row.slots)
            for row in rows
        ):
            raise ValueError(
                f"您在这些日期已预订「{resource.name}」，不能重复预订，请前往预订订单查看或变更。"
            )

    def make_quote(self, owner, rid, req):
        with sessions()() as s:
            r = s.get(Resource, rid)
        if not r:
            raise ValueError("资源不存在")
        with sessions()() as s:
            self.ensure_not_booked(
                s,
                owner,
                r,
                self.slots(r, req),
                req.order_id if req.intent == "change" else None,
            )
        candidates = self.search(r.kind, req)
        match = next((x for x in candidates if x["id"] == rid), None)
        if not match:
            raise ValueError("资源无库存或日期不匹配")
        bundle = self.knowledge.retrieve(
            Query(
                question="预订取消费用与改签条件",
                supplier=r.supplier,
                product=r.product,
                applicable_date=date.today(),
            )
        )
        if bundle.status != "SUPPORTED":
            raise ValueError("无适用政策，不能生成提案")
        with sessions().begin() as s:
            q = Quote(
                owner=owner,
                resource=rid,
                resource_version=r.version,
                revision=bundle.snapshot[0],
                amount=match["amount"],
                quantity=match["quantity"],
                slots=match["slots"],
                expires=now() + 600,
            )
            s.add(q)
            s.flush()
            return q.id, [e.model_dump() for e in bundle.evidence]

    def proposal(self, owner, req, request_id=None):
        if request_id:
            with sessions()() as s:
                existing = s.get(Proposal, request_id)
                if existing:
                    if existing.owner != owner:
                        raise ValueError("提案不存在")
                    return {
                        "id": existing.id,
                        "version": existing.version,
                        "actions": existing.actions,
                        "evidence": existing.evidence,
                        "expires": existing.expires,
                    }
        actions = []
        evidence = []
        old = self.order(owner, req.order_id) if req.order_id else None
        if req.intent in ("change", "cancel") and (
            not old or old.status != "CONFIRMED"
        ):
            raise ValueError("需要本人有效订单")
        if old:
            with sessions()() as s:
                rev = s.get(Revision, old.revision)
                if not rev or rev.status != "PUBLISHED":
                    raise ValueError("历史政策已撤回，请人工核查")
                r = s.get(Resource, old.resource)
            bundle = self.knowledge.retrieve(
                Query(
                    question="取消与改签条件",
                    supplier=r.supplier,
                    product=r.product,
                    applicable_date=date.today(),
                    revision_id=old.revision,
                )
            )
            if bundle.status != "SUPPORTED":
                raise ValueError("历史政策证据不足")
            evidence.extend(e.model_dump() for e in bundle.evidence)
        if req.intent == "cancel":
            fee = rev.rules["cancel_fee_cents"] * (
                old.quantity if r.kind == "flight" else 1
            )
            actions = [
                {
                    "kind": "cancel",
                    "order": old.id,
                    "order_version": old.version,
                    "fee": fee,
                    "revision": old.revision,
                }
            ]
        else:
            if not req.resource_ids:
                raise ValueError("请先选择资源或方案")
            if req.intent == "change" and len(req.resource_ids) != 1:
                raise ValueError("一次改签只改一个订单；联合变更需分步审批")
            for rid in req.resource_ids:
                if old:
                    with sessions()() as check:
                        original = check.get(Resource, old.resource)
                        replacement = check.get(Resource, rid)
                        if not replacement or original.kind != replacement.kind:
                            raise ValueError("改签不能改变订单业务类型")
                qid, ev = self.make_quote(owner, rid, req)
                evidence.extend(ev)
                actions.append(
                    {
                        "kind": "change" if old else "book",
                        "quote": qid,
                        "order": old.id if old else None,
                        "order_version": old.version if old else None,
                    }
                )
        with sessions().begin() as s:
            p = Proposal(
                id=request_id,
                owner=owner,
                actions=actions,
                evidence=evidence,
                expires=now() + 600,
            )
            s.add(p)
            s.flush()
            return {
                "id": p.id,
                "version": p.version,
                "actions": actions,
                "evidence": evidence,
                "expires": p.expires,
            }

    def pending(self, owner, kind, data, request_id):
        with sessions().begin() as s:
            p = s.get(Proposal, request_id)
            if p and p.owner != owner:
                raise ValueError("提案不存在")
            if not p:
                p = Proposal(
                    id=request_id,
                    owner=owner,
                    actions=[{"kind": kind, "data": data}],
                    evidence=[],
                    expires=now() + 600,
                )
                s.add(p)
                s.flush()
            return {
                "id": p.id,
                "version": p.version,
                "actions": p.actions,
                "evidence": p.evidence,
                "expires": p.expires,
            }

    def prepare_admin(self, owner, action, request_id):
        action = dict(action or {})
        with sessions()() as s:
            actor = s.get(User, owner)
            if not actor or actor.role != "admin":
                raise ValueError("仅管理员可提出后台变更")
            kind = action.get("kind")
            if kind in ("case_claim", "case_reply"):
                case = s.get(Case, action.get("case_id"))
                if not case:
                    raise ValueError("工单不存在")
                action["before"] = {
                    "status": case.status,
                    "assigned": case.assigned,
                    "replies": case.replies,
                }
            elif kind in (
                "knowledge_publish",
                "knowledge_revoke",
                "knowledge_rollback",
            ):
                revision = s.get(Revision, action.get("revision"))
                if not revision:
                    raise ValueError("版本不存在")
                action["before"] = self.revision_snapshot(s, revision.document)
            elif kind != "knowledge_import":
                raise ValueError("不支持的后台变更")
        return self.pending(owner, "admin_write", action, request_id)

    @staticmethod
    def revision_snapshot(s, document):
        return sorted(
            [
                [r.id, r.status, r.valid_from, r.valid_to]
                for r in s.scalars(
                    select(Revision).where(Revision.document == document)
                )
            ]
        )

    def decide(self, owner, pid, version, decision):
        if decision not in ("approve", "reject"):
            raise ValueError("审批决定非法")
        with sessions().begin() as s:
            p = s.scalar(select(Proposal).where(Proposal.id == pid).with_for_update())
            if not p or p.owner != owner or p.version != version:
                raise ValueError("提案不匹配")
            if p.status in ("DONE", "PARTIAL"):
                return
            if p.status != "PENDING":
                raise ValueError("提案已处理")
            if p.expires < now():
                raise ValueError("提案过期，请生成新提案")
            p.status = "APPROVED" if decision == "approve" else "REJECTED"

    def execute(self, owner, pid, run_id=None, fence=None):
        results = []
        with sessions()() as s:
            p = s.get(Proposal, pid)
            if (
                not p
                or p.owner != owner
                or p.status not in ("APPROVED", "DONE", "PARTIAL")
            ):
                raise ValueError("未批准的提案不能执行")
            actions = p.actions
        for i, action in enumerate(actions):
            op_id = f"{pid}:{i}"
            try:
                with sessions().begin() as s:
                    p = s.scalar(
                        select(Proposal).where(Proposal.id == pid).with_for_update()
                    )
                    if run_id:
                        run = s.scalar(
                            select(Run).where(Run.id == run_id).with_for_update()
                        )
                        if (
                            run.fence != fence
                            or run.lease_until < now()
                            or run.cancel_requested
                        ):
                            raise ValueError("worker 租约失效")
                    if p.owner != owner or p.status not in (
                        "APPROVED",
                        "DONE",
                        "PARTIAL",
                    ):
                        raise ValueError("未批准的提案不能执行")
                    # 同一用户的交易串行化；先锁用户再普通读取，避免旧快照漏查订单。
                    if action["kind"] in ("book", "change", "cancel"):
                        if not s.get(User, owner, with_for_update=True):
                            raise ValueError("用户不存在")
                    previous = s.get(Operation, op_id)
                    if previous:
                        results.append(previous.result)
                        continue
                    result = self._apply(s, owner, p, action)
                    s.add(Operation(id=op_id, proposal=pid, result=result))
                    results.append(result)
            except ValueError as exc:
                results.append({"status": "FAILED", "message": str(exc), "index": i})
                break
        with sessions().begin() as s:
            p = s.get(Proposal, pid)
            p.status = (
                "DONE" if all(r["status"] == "SUCCESS" for r in results) else "PARTIAL"
            )
        return results

    def _apply(self, s, owner, p, action):
        if p.expires < now():
            raise ValueError("报价或提案过期，需要重新确认")
        if p.status not in ("APPROVED", "DONE", "PARTIAL") or p.owner != owner:
            raise ValueError("未批准的提案不能执行")
        if action["kind"] in (
            "plan_create",
            "case_create",
            "case_message",
            "repair_save",
            "admin_write",
        ):
            return self._apply_content(s, owner, p, action)
        old = None
        if action.get("order"):
            old = s.scalar(
                select(Order).where(Order.id == action["order"]).with_for_update()
            )
            if (
                not old
                or old.owner != owner
                or old.status != "CONFIRMED"
                or old.version != action["order_version"]
            ):
                raise ValueError("订单已变化")
            policy = s.get(Revision, old.revision)
            if policy.status != "PUBLISHED":
                raise ValueError("政策撤回，需要重新审查")
        quote = None
        if action["kind"] != "cancel":
            quote = s.get(Quote, action["quote"])
            if not quote or quote.owner != owner or quote.expires < now():
                raise ValueError("报价已过期")
            resource = s.scalar(
                select(Resource).where(Resource.id == quote.resource).with_for_update()
            )
            if resource.version != quote.resource_version:
                raise ValueError("价格已变化")
            self.ensure_not_booked(
                s, owner, resource, quote.slots, old.id if old else None
            )
            rev = s.get(Revision, quote.revision)
            if rev.status != "PUBLISHED":
                raise ValueError("报价政策已撤回")
        slot_ids = sorted(
            set((old.slots if old else []) + (quote.slots if quote else []))
        )
        stocks = list(
            s.scalars(
                select(Inventory)
                .where(Inventory.id.in_(slot_ids))
                .order_by(Inventory.id)
                .with_for_update()
            )
        )
        if len(stocks) != len(slot_ids):
            raise ValueError("库存记录缺失")
        stock = {v.id: v for v in stocks}
        if old:
            for sid in old.slots:
                stock[sid].available += old.quantity
        if quote:
            if any(stock[sid].available < quote.quantity for sid in quote.slots):
                raise ValueError("库存不足；原订单未修改")
            for sid in quote.slots:
                stock[sid].available -= quote.quantity
        if action["kind"] == "cancel":
            old.status = "CANCELLED"
            old.version += 1
            return {"status": "SUCCESS", "order": old.id, "fee": action["fee"]}
        if old:
            difference = quote.amount - old.amount
            old.resource = quote.resource
            old.revision = quote.revision
            old.amount = quote.amount
            old.quantity = quote.quantity
            old.slots = quote.slots
            old.version += 1
            return {"status": "SUCCESS", "order": old.id, "difference": difference}
        order = Order(
            owner=owner,
            resource=quote.resource,
            revision=quote.revision,
            amount=quote.amount,
            quantity=quote.quantity,
            slots=quote.slots,
        )
        s.add(order)
        s.flush()
        return {"status": "SUCCESS", "order": order.id, "amount": order.amount}

    def plan_draft(self, owner, req, results):
        flights = results.get("flight", {}).get("candidates", [])
        hotels = results.get("hotel", {}).get("candidates", [])
        if not flights or not hotels:
            raise ValueError("无法组成行程：请调整日期或目的地")
        evidence = self.knowledge.retrieve(
            Query(
                question=f"{req.destination}行程活动与延期注意事项",
                supplier="目的地指南",
                product=req.destination,
                applicable_date=req.start,
            )
        )
        options = []
        for flight in flights:
            for hotel in hotels:
                total = flight["amount"] + hotel["amount"]
                if total <= req.budget_cents:
                    options.append(
                        {
                            "label": f'{flight["name"]} + {hotel["name"]}',
                            "resource_ids": [flight["id"], hotel["id"]],
                            "amount": total,
                            "start": str(req.start),
                            "end": str(req.end),
                            "people": req.people,
                            "budget_cents": req.budget_cents,
                            "scope": "仅机票与酒店；餐饮、当地交通和景点费用未计入",
                            "evidence": evidence.model_dump(),
                            "days": [],
                        }
                    )
        if not options:
            raise ValueError("预算不足，请提高预算或调整需求")
        return {"options": sorted(options, key=lambda o: o["amount"])}

    def validate_plan(self, req, draft, design, run_id):
        feasible = {frozenset(o["resource_ids"]): o for o in draft["options"]}
        output, used = [], set()
        for selected in design.options:
            pair = frozenset(selected.resource_ids)
            if pair not in feasible or pair in used:
                raise ValueError("规划结果不在可行组合中或重复")
            used.add(pair)
            option = dict(feasible[pair])
            ids = {e["node_id"] for e in option["evidence"]["evidence"]}
            dates = set()
            for day in selected.days:
                if not req.start <= day.date < req.end or day.date in dates:
                    raise ValueError("规划活动日期越界或重复")
                if not day.evidence_ids or not set(day.evidence_ids) <= ids:
                    raise ValueError("规划活动缺少有效知识出处")
                dates.add(day.date)
            option.update(
                option_id=f"{run_id}:{len(output) + 1}",
                label=selected.label,
                explanation=selected.explanation,
                days=[d.model_dump(mode="json") for d in selected.days],
            )
            output.append(option)
        return {"options": output}

    def _apply_content(self, s, owner, p, action):
        kind, data = action["kind"], action["data"]
        if kind == "plan_create":
            plan = Plan(id=p.id, owner=owner, options=data["options"])
            s.add(plan)
            return {"status": "SUCCESS", "plan": {"id": p.id, **data}}
        if kind == "case_create":
            case = Case(id=p.id, owner=owner, request_id=p.id, context=data)
            s.add(case)
            return {"status": "SUCCESS", "case_id": p.id}
        if kind == "case_message":
            case = s.scalar(
                select(Case)
                .where(Case.id == data["request"]["case_id"])
                .with_for_update()
            )
            if not case or case.owner != owner or case.status == "CLOSED":
                raise ValueError("服务申请不存在或已经结束")
            case.replies = [
                *case.replies,
                {
                    "by": owner,
                    "role": "user",
                    "text": data["request"]["question"],
                    "at": now(),
                },
            ]
            return {"status": "SUCCESS", "case_id": case.id}
        if kind == "repair_save":
            original = s.scalar(
                select(Plan).where(Plan.id == data["plan_id"]).with_for_update()
            )
            if (
                not original
                or original.owner != owner
                or original.options != data["report"]["diff"]["before"]
            ):
                raise ValueError("原行程已变化，请重新研究并确认")
            folder = settings().artifact_dir / owner / p.id
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / "report.pending"
            temporary.write_text(json.dumps(data["report"], ensure_ascii=False))
            temporary.replace(folder / "report.json")
            return {"status": "SUCCESS", "repair": data["report"]}
        actor = s.get(User, owner)
        if not actor or actor.role != "admin":
            raise ValueError("管理员权限已失效")
        change = data["kind"]
        if change in ("case_claim", "case_reply"):
            case = s.scalar(
                select(Case).where(Case.id == data["case_id"]).with_for_update()
            )
            if (
                not case
                or {
                    "status": case.status,
                    "assigned": case.assigned,
                    "replies": case.replies,
                }
                != data["before"]
            ):
                raise ValueError("工单已变化，请重新确认")
            if case.status == "CLOSED":
                raise ValueError("工单已关闭")
            if change == "case_claim":
                if case.assigned and case.assigned != owner:
                    raise ValueError("已被领取")
                case.assigned, case.status = owner, "PROCESSING"
            else:
                if case.assigned != owner:
                    raise ValueError("请先领取工单")
                case.replies = [*case.replies, {"by": owner, "text": data["text"]}]
                if data["close"]:
                    case.status = "CLOSED"
            return {"status": "SUCCESS", "case_id": case.id, "case_status": case.status}
        if change == "knowledge_import":
            content = base64.b64decode(data["content_base64"], validate=True)
            folder = (
                settings().artifact_dir
                / "imports"
                / hashlib.sha256(content).hexdigest()
            )
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / data["name"]
            path.write_bytes(content)
            result = self.knowledge.import_document(path, data["metadata"])
        else:
            revision = s.get(Revision, data["revision"])
            if (
                not revision
                or self.revision_snapshot(s, revision.document) != data["before"]
            ):
                raise ValueError("知识版本已变化，请重新确认")
            {
                "knowledge_publish": self.knowledge.publish,
                "knowledge_revoke": self.knowledge.revoke,
                "knowledge_rollback": self.knowledge.rollback,
            }[change](data["revision"])
            result = {"revision": data["revision"]}
        return {"status": "SUCCESS", "knowledge": result}
