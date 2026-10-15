from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Query(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    supplier: str
    product: str
    applicable_date: date
    revision_id: str | None = None


class Evidence(BaseModel):
    node_id: str
    revision_id: str
    source: str
    section: str
    text: str
    score: float


class EvidenceBundle(BaseModel):
    status: Literal["SUPPORTED", "INSUFFICIENT", "CONFLICTING"]
    snapshot: list[str]
    evidence: list[Evidence]


class Task(BaseModel):
    id: str
    role: Literal["flight", "hotel"]
    depends_on: list[str] = Field(default_factory=list)


class Request(BaseModel):
    intent: Literal[
        "policy",
        "search",
        "plan",
        "book",
        "change",
        "cancel",
        "support",
        "repair",
        "admin_write",
    ]
    # 仅管理员专用 HTTP 入口可提交；普通消息入口禁止此意图。
    admin_action: dict | None = None
    question: str = "取消政策是什么？"
    departure: str = "北京"
    destination: str = "上海"
    start: date | None = None
    end: date | None = None
    people: int = Field(default=1, ge=1, le=6)
    budget_cents: int = Field(default=600000, gt=0)
    resource_ids: list[str] = Field(default_factory=list, max_length=2)
    order_id: str | None = None
    plan_id: str | None = None
    proposal_id: str | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.start and self.end and not 0 < (self.end - self.start).days <= 14:
            raise ValueError("住宿需 1—14 晚，退房日期必须晚于入住")
        return self


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    request: Request | None = None


class RepairOption(BaseModel):
    label: str
    resource_ids: list[str]
    start: date
    end: date
    explanation: str
    evidence_ids: list[str]


class RepairReport(BaseModel):
    options: list[RepairOption] = Field(min_length=2, max_length=2)
    unresolved: list[str] = Field(default_factory=list)


def validate_tasks(tasks: list[Task]):
    if len(tasks) > 6 or len({t.id for t in tasks}) != len(tasks):
        raise ValueError("任务数量或 ID 非法")
    waiting = {t.id: set(t.depends_on) for t in tasks}
    done = set()
    while waiting:
        ready = [k for k, v in waiting.items() if v <= done]
        if not ready:
            raise ValueError("任务有环或依赖不存在")
        for k in ready:
            done.add(k)
            del waiting[k]
    return tasks


def merge_results(left: dict, right: dict):
    result = dict(left)
    for k, v in right.items():
        if k in result and result[k] != v:
            raise ValueError(f"任务结果冲突: {k}")
        result[k] = v
    return result


class PolicyRules(BaseModel):
    cancel_fee_cents: int = Field(ge=0)


class PolicyMetadata(BaseModel):
    document: str = Field(min_length=1, max_length=100)
    supplier: str = Field(min_length=1, max_length=100)
    product: str = Field(min_length=1, max_length=60)
    valid_from: date
    valid_to: date
    rules: PolicyRules

    @model_validator(mode="after")
    def valid_dates(self):
        if self.valid_to < self.valid_from:
            raise ValueError("政策有效期非法")
        return self
