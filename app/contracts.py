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


class Request(BaseModel):
    intent: Literal[
        "chat",
        "orders",
        "plans",
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
    admin_action: dict | None = None
    question: str = ""
    resolved_question: str | None = Field(default=None, max_length=2000)
    departure: str = "北京"
    destination: str = "上海"
    start: date | None = None
    end: date | None = None
    people: int = Field(default=1, ge=1, le=6)
    budget_cents: int = Field(default=600000, gt=0)
    resource_ids: list[str] = Field(default_factory=list, max_length=2)
    resource_kinds: list[Literal["flight", "hotel"]] = Field(
        default_factory=lambda: ["flight", "hotel"], min_length=1, max_length=2
    )
    option_id: str | None = None
    order_id: str | None = None
    plan_id: str | None = None
    proposal_id: str | None = None
    case_id: str | None = None

    @model_validator(mode="after")
    def dates(self):
        if len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValueError("同一请求不能重复选择同一资源")
        if self.start and self.end and not 0 < (self.end - self.start).days <= 14:
            raise ValueError("住宿需 1—14 晚，退房日期必须晚于入住")
        return self


class TurnParameters(BaseModel):
    """对话中的业务信息。没有业务默认值，不代表执行已经获准。"""

    departure: str | None = None
    destination: str | None = None
    start: date | None = None
    end: date | None = None
    people: int | None = Field(default=None, ge=1, le=6)
    budget_cents: int | None = Field(default=None, gt=0)
    resource_ids: list[str] | None = Field(default=None, max_length=2)
    resource_kinds: list[Literal["flight", "hotel"]] | None = None
    order_id: str | None = None
    plan_id: str | None = None
    option_id: str | None = None


class TurnUnderstanding(BaseModel):
    """本轮对话理解结果；进入业务层时再构造 Request。"""

    intent: Literal[
        "chat",
        "orders",
        "plans",
        "policy",
        "search",
        "plan",
        "repair",
        "book",
        "change",
        "cancel",
        "support",
    ]
    resolved_question: str = Field(
        min_length=1, max_length=2000, description="结合对话展开后的本轮需求"
    )
    parameters: TurnParameters = Field(
        default_factory=TurnParameters,
        description="当前目标相关的已知业务信息；只填写有依据的值",
    )
    selected_option_index: int | None = Field(
        default=None, ge=1, description="仅表示已生成旅行方案中的选择序号；其他选择不填"
    )


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


class CandidateReview(BaseModel):
    ranked_ids: list[str] = Field(min_length=1, max_length=3)
    reasoning: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class DayActivity(BaseModel):
    date: date
    activity: str
    evidence_ids: list[str] = Field(default_factory=list)


class PlannedOption(BaseModel):
    resource_ids: list[str] = Field(min_length=2, max_length=2)
    label: str
    explanation: str
    days: list[DayActivity] = Field(default_factory=list)


class PlanDesign(BaseModel):
    options: list[PlannedOption] = Field(min_length=1, max_length=2)
