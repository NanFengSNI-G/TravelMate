import type { Resource, Run, PlanOption, RequestData } from "./types";
export const money = (cents = 0) =>
  new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: cents % 100 ? 2 : 0,
  }).format(cents / 100);
export const dateLabel = (value?: string) =>
  value
    ? new Date(value + "T00:00:00").toLocaleDateString("zh-CN", {
        month: "long",
        day: "numeric",
      })
    : "待确认";
export const rangeLabel = (start?: string, end?: string) =>
  `${dateLabel(start)} — ${dateLabel(end)}`;
export const addDays = (value: string, days: number) => {
  const date = new Date(value + "T12:00:00");
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
export const nights = (start: string, end: string) =>
  Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86400000);
export const active = (run?: Run | null) =>
  !!run && ["QUEUED", "RUNNING", "WAITING"].includes(run.status);
export const statusLabels: Record<string, string> = {
  QUEUED: "已提交",
  RUNNING: "正在处理",
  WAITING: "待您确认",
  DONE: "已完成",
  FAILED: "未能完成",
  CANCELLED: "已停止",
  CONFIRMED: "预订确认",
  OPEN: "等待客服",
  PROCESSING: "服务中",
  CLOSED: "已结束",
  PUBLISHED: "已发布",
  VERIFIED: "待发布",
  REVOKED: "已撤回",
  INDEXING: "导入中",
};
export const intentLabels: Record<string, string> = {
  chat: "日常交流",
  orders: "本人订单",
  plans: "已有行程",
  policy: "政策咨询",
  search: "资源查询",
  plan: "行程规划",
  book: "旅行预订",
  change: "订单变更",
  cancel: "取消预订",
  support: "人工服务",
  repair: "行程调整",
  admin_write: "管理操作",
};
export function tripDestination(option: PlanOption, resources: Resource[]) {
  return (
    resources.find((r) => option.resource_ids.includes(r.id))?.details
      .destination || "旅行方案"
  );
}
export function requestForOption(
  option: PlanOption,
  intent: RequestData["intent"] = "book",
): RequestData {
  return {
    intent,
    start: option.start,
    end: option.end,
    people: option.people || 1,
    budget_cents: option.budget_cents || 600000,
    resource_ids: option.resource_ids,
    question: "预订选定的旅行方案",
  };
}
export function orderDates(slots: string[], resource?: Resource) {
  const dates = slots
    .map((slot) => slot.match(/\d{4}-\d{2}-\d{2}$/)?.[0])
    .filter((value): value is string => !!value)
    .sort();
  return dates.length
    ? { start: dates[0], end: addDays(dates[dates.length - 1], 1) }
    : { start: resource?.details.date, end: resource?.details.date };
}
export function friendlyError(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  if (/Recursion limit|GraphRecursionError/i.test(text))
    return "这次研究未能在限定步骤内完成。原行程和订单保持不变，您可以调整条件后重试，或联系人工客服。";
  if (
    /API.key|api_key|TRAVELMATE|Authentication|Connection refused|Connection error|Server disconnected|ECONNREFUSED|Internal Server/i.test(
      text,
    )
  )
    return "服务暂时不可用，请稍后重试或联系管理员。";
  return text;
}

export function bookingMessage(
  option: PlanOption,
  index: number,
  resources: Resource[],
) {
  const names = option.resource_ids
    .map((id) => resources.find((r) => r.id === id)?.name || "已选资源")
    .join("、");
  return `我选择方案 ${index + 1}「${option.label}」：${names}；出行日期 ${option.start} 至 ${option.end}${option.people ? `，${option.people} 人` : ""}${option.amount !== undefined ? `，机票与住宿合计 ${money(option.amount)}` : ""}。请核对预订报价。`;
}
