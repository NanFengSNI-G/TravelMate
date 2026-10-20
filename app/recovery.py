import json
import re
from datetime import date
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.tools import tool
from langchain.agents.structured_output import ToolStrategy
from langchain.agents.middleware import wrap_model_call, TodoListMiddleware
from deepagents.profiles import (
    HarnessProfile,
    GeneralPurposeSubagentProfile,
    register_harness_profile,
)
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from pydantic import model_validator
from app.agents import model
from app.conversations import messages as conversation_messages
from app.config import settings
from app.contracts import RepairReport as ReportSchema, Query
from app.db import sessions
from app.models import Plan

register_harness_profile(
    "openai:qwen3.7-flash",
    HarnessProfile(
        excluded_tools=frozenset({"ls", "glob", "grep", "execute"}),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ),
)


class ResearchUnavailable(ValueError):
    """候选不足属于可调整条件的业务结果。"""


class Recovery:
    def __init__(self, domain, saver):
        self.domain = domain
        self.saver = saver

    def run(self, owner, run_id, req):
        if not re.fullmatch(r"[a-zA-Z0-9-]+", owner + run_id):
            raise ValueError("工作空间 ID 非法")
        with sessions()() as s:
            old = s.get(Plan, req.plan_id)
            if not old or old.owner != owner:
                raise ValueError("请提供本人已有行程")
            original = old.options
        root = settings().artifact_dir / ".drafts" / owner / run_id
        root.mkdir(parents=True, exist_ok=True)
        original_file = root / "original_plan.json"
        if not original_file.exists():
            fields = {
                "resource_ids",
                "label",
                "start",
                "end",
                "people",
                "amount",
                "days",
            }
            original_file.write_text(
                json.dumps(
                    [
                        {k: v for k, v in option.items() if k in fields}
                        for option in original
                    ],
                    ensure_ascii=False,
                )
            )

        @tool
        def research_transport() -> str:
            """只读查询新日期的交通与酒店候选。"""
            return json.dumps(
                {
                    "currency": "CNY",
                    "amount_unit": "分",
                    "amount_scope": "amount 是当前日期、人数的合计费用，酒店已包含全部晚数，不是每晚单价",
                    "flight": self.domain.search("flight", req),
                    "hotel": self.domain.search("hotel", req),
                    "policies": policies,
                    "feasible_combinations": combinations,
                },
                ensure_ascii=False,
            )

        @tool
        def research_destination() -> str:
            """读取目标城市的延期修复指南，带版本与出处。"""
            return self.domain.knowledge.retrieve(
                Query(
                    question="延期修复",
                    supplier="目的地指南",
                    product=req.destination,
                    applicable_date=req.start or date.today(),
                )
            ).model_dump_json()

        flights = self.domain.search("flight", req)
        hotels = self.domain.search("hotel", req)
        if not flights or len(hotels) < 2:
            raise ResearchUnavailable(
                "当前日期需要至少一个可用航班和两家可用酒店，但库存不足以形成两套方案"
            )
        combinations = [
            {
                "resource_ids": [flight["id"], hotel["id"]],
                "amount_cents": flight["amount"] + hotel["amount"],
            }
            for flight in flights
            for hotel in hotels
            if flight["amount"] + hotel["amount"] <= req.budget_cents
        ]
        if len(combinations) < 2:
            raise ResearchUnavailable("当前预算无法形成两套不同资源组合")
        constraints = req.model_dump(
            mode="json",
            include={
                "departure",
                "destination",
                "start",
                "end",
                "people",
                "budget_cents",
            },
        )
        constraints.update(
            selection_rule="两套方案按资源组合区分，可以共用航班、选择不同酒店；原资源只是历史参考，新资源从可行集合选择。金额单位分。",
            feasible_combinations=combinations,
        )
        (root / "constraints.json").write_text(
            json.dumps(constraints, ensure_ascii=False)
        )
        ev = self.domain.knowledge.retrieve(
            Query(
                question="延期修复",
                supplier="目的地指南",
                product=req.destination,
                applicable_date=req.start or date.today(),
            )
        )
        policies = {}
        product_policies = {}
        for candidate in flights + hotels:
            identity = (candidate["supplier"], candidate["product"])
            if identity not in product_policies:
                product_policies[identity] = self.domain.knowledge.retrieve(
                    Query(
                        question="取消费用与日期变更限制",
                        supplier=identity[0],
                        product=identity[1],
                        applicable_date=date.today(),
                    )
                ).model_dump()
            policies[candidate["id"]] = product_policies[identity]

        @wrap_model_call
        def require_research_plan(request, handler):
            # 原生 write_todos 返回 Command 并更新 todos；其 ToolMessage 不保证带 name。
            if not request.state.get("todos"):
                return handler(
                    request.override(
                        tool_choice={
                            "type": "function",
                            "function": {"name": "write_todos"},
                        }
                    )
                )
            return handler(request)

        def readonly_research(read_tool, prompt):
            @wrap_model_call
            def require_read(request, handler):
                if not any(
                    isinstance(m, ToolMessage) and m.name == read_tool.name
                    for m in request.messages
                ):
                    return handler(
                        request.override(
                            tool_choice={
                                "type": "function",
                                "function": {"name": read_tool.name},
                            }
                        )
                    )
                return handler(request)

            return create_agent(
                model=model(),
                tools=[read_tool],
                system_prompt=prompt,
                middleware=[require_read],
            )

        class RepairReport(ReportSchema):
            @model_validator(mode="after")
            def validate_research(self):
                pairs = set()
                for option in self.options:
                    pair = frozenset(option.resource_ids)
                    if pair in pairs or not any(
                        pair == frozenset(c["resource_ids"]) for c in combinations
                    ):
                        raise ValueError("从 constraints.json 选择两套不同可行组合")
                    pairs.add(pair)
                    if option.start != req.start or option.end != req.end:
                        raise ValueError("日期必须与 constraints.json 一致")
                    allowed = {e.node_id for e in ev.evidence} | {
                        e["node_id"]
                        for rid in option.resource_ids
                        for e in policies[rid]["evidence"]
                    }
                    if not set(option.evidence_ids) <= allowed:
                        raise ValueError(
                            "仅引用本方案资源的政策或目的地指南 node_id，可用值："
                            + json.dumps(sorted(allowed), ensure_ascii=False)
                        )
                return self

        agent = create_deep_agent(
            model=model(),
            response_format=ToolStrategy(RepairReport),
            system_prompt="根据工作区根目录 /original_plan.json、/constraints.json 研究两套修复。必须分配 transport 和 destination 子助手、使用任务清单，并用 write_file 在绝对虚拟路径 /repair_plan.json 保存研究草稿。不要将正式草稿写进 /large_tool_results/。不得预编造候选、费用或证据。工具 amount 以分计，酒店已经包含全部晚数，不能再乘晚数；预算也是分。explanation 只写定性取舍，不写价格数字或指南未证明的活动。两套方案必须是不同资源组合、满足日期与预算；缺失证据或预约信息写入 unresolved。最终以结构化 RepairReport 为准；校验反馈后纠正结构化结果即可，不必反复修改研究草稿。资源名称读取 name，不用内部 ID 命名方案，也不要把工具已有的名称说成未知。只允许研究，不可交易。schema:"
            + json.dumps(RepairReport.model_json_schema()),
            tools=[],
            middleware=[TodoListMiddleware(), require_research_plan],
            backend=FilesystemBackend(root_dir=root, virtual_mode=True),
            permissions=[
                FilesystemPermission(
                    operations=["write"],
                    paths=["/original_plan.json", "/constraints.json"],
                    mode="deny",
                )
            ],
            subagents=[
                {
                    "name": "transport",
                    "description": "交通住宿研究",
                    "runnable": readonly_research(
                        research_transport,
                        "读取 research_transport，返回候选资源 ID、name、amount、quantity 和适用政策证据；保留名称，不遗漏已有事实。amount 单位为分，是当前人数和日期的合计，酒店已含全部晚数。不能重新计算或猜测单价；退改限制只引用 policies 中的证据，没有证据明确说明未知。不访问文件、不执行交易。",
                    ),
                },
                {
                    "name": "destination",
                    "description": "活动修复研究",
                    "runnable": readonly_research(
                        research_destination,
                        "读取 research_destination，返回指南原文要点和对应 node_id。不要添加原文没有的景点、活动或预约状态。不访问文件、不执行交易。",
                    ),
                },
            ],
            checkpointer=self.saver,
        )
        cfg = {
            "configurable": {"thread_id": run_id + "-recovery"},
            # 限制统计的是图步骤（含 TodoList 的前后钩子），不是模型调用次数。
            "recursion_limit": 64,
        }
        snapshot = agent.get_state(cfg)
        if snapshot.values and not snapshot.next:
            result = snapshot.values
        else:
            result = agent.invoke(
                (
                    None
                    if snapshot.values
                    else {
                        "messages": conversation_messages(
                            None,
                            "目标：根据新约束研究两套已有行程的替代方案，不处理原订单。请先读取 /original_plan.json 和 /constraints.json。用户补充需求："
                            + (req.resolved_question or req.question),
                        )
                    }
                ),
                cfg,
            )
        response = result["structured_response"]
        parsed = ReportSchema.model_validate(
            response.model_dump() if isinstance(response, ReportSchema) else response
        )
        options = []
        used = set()
        for option in parsed.options:
            if option.start != req.start or option.end != req.end:
                raise ValueError("修复日期违背约束")
            resources = option.resource_ids
            pair = frozenset(resources)
            if pair in used:
                raise ValueError("两套调整方案不能使用重复资源组合")
            used.add(pair)
            if len(resources) != 2:
                raise ValueError("需要航班和酒店")
            selected = [r for r in flights + hotels if r["id"] in resources]
            if len(selected) != 2 or {r["kind"] for r in selected} != {
                "flight",
                "hotel",
            }:
                raise ValueError("修复引用了无效资源")
            if sum(r["amount"] for r in selected) > req.budget_cents:
                raise ValueError("修复超预算")
            supporting = [e.model_dump() for e in ev.evidence] + [
                e for resource in resources for e in policies[resource]["evidence"]
            ]
            if any(
                eid not in {e["node_id"] for e in supporting}
                for eid in option.evidence_ids
            ):
                raise ValueError("修复引用无效证据")
            options.append(
                {
                    **option.model_dump(mode="json"),
                    "option_id": f"{run_id}:{len(options) + 1}",
                    "amount": sum(r["amount"] for r in selected),
                    "people": req.people,
                    "budget_cents": req.budget_cents,
                    "scope": "费用来自当前库存，仅含机票与全部住宿；已有订单不会自动变更",
                    "evidence": {
                        "status": "SUPPORTED" if supporting else "INSUFFICIENT",
                        "snapshot": sorted({e["revision_id"] for e in supporting}),
                        "evidence": list(
                            {e["node_id"]: e for e in supporting}.values()
                        ),
                    },
                }
            )
        calls = [
            call
            for message in result["messages"]
            for call in getattr(message, "tool_calls", [])
        ]
        delegated = {
            call.get("args", {}).get("subagent_type")
            for call in calls
            if call.get("name") == "task"
        }
        if not {"transport", "destination"} <= delegated:
            raise ValueError("研究未完成两个专业子助手的委派")
        if not any(call.get("name") == "write_todos" for call in calls):
            raise ValueError("研究尚未建立任务清单")
        draft_file = root / "repair_plan.json"
        if not draft_file.exists():
            raise ValueError("研究未保存 repair_plan.json 草稿")
        trace = [
            {
                "role": m.type,
                "calls": getattr(m, "tool_calls", []),
                "content": str(m.content),
            }
            for m in result["messages"]
        ]
        artifact = {
            "options": options,
            "unresolved": parsed.unresolved,
            "diff": {"before": original, "after": options},
            "trace": trace,
        }
        (root / "report.draft.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2)
        )
        return artifact
