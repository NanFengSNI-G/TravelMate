NODE_LABELS = {
    "context": "已核对本轮需求与会话信息",
    "customer": "旅行客服已完成需求处理",
    "search": "已查询所需资源与库存",
    "policy": "已完成适用政策检索与证据回答",
    "planning": "航班与酒店专家已完成比较，规划方案已校验",
    "repair": "复杂调整研究已完成，正式报告等待确认",
    "prepare": "已核对操作目标并准备确认内容",
    "approval": "已记录您的确认决定",
    "execute": "已完成本次执行与结果核验",
    "flight": "航班专家已完成候选比较",
    "hotel": "酒店专家已完成候选比较",
    "feasibility": "已核对组合库存与预算可行性",
    "compose": "已生成并校验行程安排",
    "prepare_plan": "旅行方案已准备，等待确认保存",
    "retrieve": "已检索并重排适用政策证据",
    "answer": "已根据适用政策生成回答",
    "research": "调整研究已完成并校验替代方案",
    "prepare_report": "调整报告已准备，等待确认保存",
}
TOOL_LABELS = {
    "get_travel_catalog": "核对可选城市与日期目录",
    "get_my_orders": "读取本人订单",
    "get_my_plans": "读取本人已保存行程",
    "get_pending_proposals": "核对待确认报价与费用差额",
    "retrieve_policy": "检索适用政策与回答依据",
    "search_resources": "查询可用资源与日期库存",
}


def progress_steps(payload, sequence):
    steps = []
    if not isinstance(payload, dict):
        return steps
    for node, value in payload.items():
        if node not in NODE_LABELS or not isinstance(value, dict):
            continue
        label = NODE_LABELS[node]
        tools = []
        if node == "customer":
            if value.get("stopped"):
                label = "需要补充出行信息"
            trace = value.get("customer", {}).get("trace", [])
            last = max(
                (i for i, m in enumerate(trace) if m.get("role") == "human"), default=-1
            )
            calls = [call for m in trace[last + 1 :] for call in m.get("calls", [])]
            for name, title in TOOL_LABELS.items():
                count = sum(call.get("name") == name for call in calls)
                if count:
                    tools.append({"label": title, "count": count})
        if node == "planning":
            count = sum(
                item.get("tool_calls", 0) for item in value.get("results", {}).values()
            )
            if count:
                tools.append({"label": TOOL_LABELS["search_resources"], "count": count})
        if node == "execute":
            operations = value.get("outcome", {}).get("operations", [])
            if any(item.get("status") != "SUCCESS" for item in operations):
                label = "已完成核验，部分操作未执行成功"
        steps.append(
            {"id": f"{sequence}:{node}", "node": node, "label": label, "tools": tools}
        )
    return steps


def public_event(event):
    steps = (
        progress_steps(event.get("payload"), event["sequence"])
        if event["type"] == "progress"
        else []
    )
    return {
        "sequence": event["sequence"],
        "type": event["type"],
        "payload": {s["node"]: s for s in steps},
    }
