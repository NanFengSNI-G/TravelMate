import json
import re
from datetime import date
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.tools import tool
from langchain.agents.structured_output import ToolStrategy
from app.agents import model
from app.config import settings
from app.contracts import RepairReport, Query
from app.db import sessions
from app.models import Plan


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
        # 仅内部研究草稿；Agent 没有正式报告目录和业务数据库写工具。
        root = settings().artifact_dir / ".drafts" / owner / run_id
        root.mkdir(parents=True, exist_ok=True)
        original_file = root / "original_plan.json"
        if not original_file.exists():
            original_file.write_text(json.dumps(original, ensure_ascii=False))
        (root / "constraints.json").write_text(req.model_dump_json())

        @tool
        def research_transport() -> str:
            """只读查询新日期的交通与酒店候选。"""
            return json.dumps(
                {
                    "flight": self.domain.search("flight", req),
                    "hotel": self.domain.search("hotel", req),
                },
                ensure_ascii=False,
            )

        @tool
        def research_destination() -> str:
            """读取上海延期修复指南，带版本与出处。"""
            return self.domain.knowledge.retrieve(
                Query(
                    question="延期修复",
                    supplier="目的地指南",
                    product="上海",
                    applicable_date=date.today(),
                )
            ).model_dump_json()

        flights = self.domain.search("flight", req)
        hotels = self.domain.search("hotel", req)
        if not flights or len(hotels) < 2:
            raise ValueError("备选不足，返回客服调整条件")
        ev = self.domain.knowledge.retrieve(
            Query(
                question="延期修复",
                supplier="目的地指南",
                product="上海",
                applicable_date=date.today(),
            )
        )
        report = {
            "options": [
                {
                    "label": h["name"],
                    "resource_ids": [flights[0]["id"], h["id"]],
                    "start": str(req.start),
                    "end": str(req.end),
                    "explanation": "保留博物馆活动顺序，压缩抵达日安排；预约和交通时间需核实。",
                    "evidence_ids": [e.node_id for e in ev.evidence],
                }
                for h in hotels[:2]
            ],
            "unresolved": ["景点预约未接真实服务"],
        }
        output = json.dumps(report, ensure_ascii=False)
        todos = [
            {"content": "研究交通住宿", "status": "in_progress"},
            {"content": "修复活动安排", "status": "pending"},
        ]
        script = [
            {"name": "read_file", "args": {"file_path": "/original_plan.json"}},
            {"name": "write_todos", "args": {"todos": todos}},
            {
                "name": "task",
                "args": {
                    "description": "研究交通住宿替代，返回资源与费用",
                    "subagent_type": "transport",
                },
            },
            {
                "name": "task",
                "args": {
                    "description": "研究延期后的活动安排，返回证据 ID",
                    "subagent_type": "destination",
                },
            },
            {
                "name": "write_file",
                "args": {"file_path": "/repair_plan.json", "content": output},
            },
            {
                "name": "write_todos",
                "args": {
                    "todos": [
                        {"content": t["content"], "status": "completed"} for t in todos
                    ]
                },
            },
        ]
        agent = create_deep_agent(
            model=model(script, output, structured=report),
            response_format=ToolStrategy(RepairReport),
            system_prompt="根据原行程、约束研究两套修复。必须分配研究子助手、使用任务清单、保存 repair_plan.json。最后仅输出 RepairReport JSON。不可交易。schema:"
            + json.dumps(RepairReport.model_json_schema()),
            tools=[],
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
                    "system_prompt": "调用 research_transport，返回资源 ID 和费用。",
                    "tools": [research_transport],
                    "model": model(
                        [{"name": "research_transport", "args": {}}],
                        json.dumps(
                            {"flight": flights, "hotel": hotels}, ensure_ascii=False
                        ),
                    ),
                },
                {
                    "name": "destination",
                    "description": "活动修复研究",
                    "system_prompt": "调用 research_destination，返回证据 ID。",
                    "tools": [research_destination],
                    "model": model(
                        [{"name": "research_destination", "args": {}}],
                        ev.model_dump_json(),
                    ),
                },
            ],
            checkpointer=self.saver,
        )
        cfg = {
            "configurable": {"thread_id": run_id + "-recovery"},
            "recursion_limit": 40,
        }
        snapshot = agent.get_state(cfg)
        if snapshot.values and not snapshot.next:
            result = snapshot.values
        else:
            result = agent.invoke(
                (
                    None
                    if snapshot.values
                    else {"messages": [("user", req.model_dump_json())]}
                ),
                cfg,
            )
        parsed = result["structured_response"]
        options = []
        for option in parsed.options:
            if option.start != req.start or option.end != req.end:
                raise ValueError("修复日期违背约束")
            resources = option.resource_ids
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
            if any(
                eid not in {e.node_id for e in ev.evidence}
                for eid in option.evidence_ids
            ):
                raise ValueError("修复引用无效证据")
            options.append(option.model_dump(mode="json"))
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
