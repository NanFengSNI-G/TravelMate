import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { Run } from "./types";

const BASE = (
  (import.meta as ImportMeta & { env: Record<string, string> }).env
    .VITE_API_BASE_URL || "http://127.0.0.1:18080"
).replace(/\/$/, "");
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export async function api<T = any>(
  path: string,
  token = "",
  body?: unknown,
  signal?: AbortSignal,
  method?: "GET" | "POST" | "PATCH" | "DELETE",
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError("暂时无法连接服务，请稍后重试。", 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((item: { msg: string }) => item.msg).join("；")
          : "操作暂未完成，请重试。";
    throw new ApiError(
      response.status === 401 ? "登录已过期，请重新登录。" : detail,
      response.status,
    );
  }
  return data as T;
}
export async function followRun(
  id: string,
  token: string,
  signal: AbortSignal,
  onProgress: (label: string) => void,
  onUpdate: (run: Run) => void,
) {
  let retries = 0;
  const stages: Record<string, string> = {
    customer: "已理解需求，正在安排",
    context: "正在核对会话与需求",
    search: "正在查询资源与日期库存",
    policy: "正在核对适用政策与证据",
    planning: "正在比较航班、酒店并校验方案",
    repair: "正在研究复杂调整方案",
    prepare: "正在准备待确认内容",
    approval: "方案已就绪，等待您的确认",
    execute: "正在执行您确认的操作",
    finish: "正在汇总处理结果",
  };
  const finish = async () =>
    onUpdate(await api<Run>(`/api/runs/${id}`, token, undefined, signal));
  try {
    await fetchEventSource(BASE + `/api/runs/${id}/events`, {
      headers: { Authorization: "Bearer " + token },
      signal,
      openWhenHidden: true,
      async onopen(response) {
        if (
          !response.ok ||
          !response.headers.get("content-type")?.includes("text/event-stream")
        )
          throw new ApiError("进度连接暂时不可用", response.status);
      },
      async onmessage(message) {
        if (message.event === "complete") {
          await finish();
          return;
        }
        if (!message.data) return;
        const event = JSON.parse(message.data);
        if (event.type === "progress") {
          for (const [key, step] of Object.entries(event.payload || {})) {
            const label = (step as { label?: string }).label;
            if (label || stages[key]) onProgress(label || stages[key]);
          }
          await finish();
        }
        if (event.type === "approval" || event.type === "result")
          await finish();
      },
      onclose() {},
      onerror(error) {
        if (
          signal.aborted ||
          (error instanceof ApiError && error.status === 401) ||
          ++retries >= 3
        )
          throw error;
        return 1500;
      },
    });
  } catch (error) {
    if (!signal.aborted) {
      onProgress("正在重新获取处理进度");
      await finish();
    }
  }
}
