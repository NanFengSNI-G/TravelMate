import { fetchEventSource } from "@microsoft/fetch-event-source";

const BASE = "http://127.0.0.1:18080";
export async function api(path: string, token: string, body?: unknown) {
  const response = await fetch(BASE + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.detail || "请求失败");
  return data;
}
class FatalEventError extends Error {}

export async function followRun(
  id: string,
  token: string,
  onEvent: (e: Record<string, unknown>) => void,
) {
  const controller = new AbortController();
  let cursor = 0;
  let complete = false;
  let retries = 0;
  await fetchEventSource(BASE + `/api/runs/${id}/events`, {
    headers: { Authorization: "Bearer " + token },
    signal: controller.signal,
    openWhenHidden: true,
    async onopen(response) {
      if (response.status >= 400 && response.status < 500) {
        throw new FatalEventError("事件订阅被拒绝，请重新登录或检查运行归属");
      }
      if (!response.ok || !response.headers.get("content-type")?.includes("text/event-stream")) {
        throw new Error("事件服务暂不可用");
      }
    },
    onmessage(message) {
      if (message.event === "complete") {
        complete = true;
        controller.abort();
        return;
      }
      if (!message.data) return;
      const event = JSON.parse(message.data);
      if (event.sequence > cursor) {
        cursor = event.sequence;
        onEvent(event);
      }
    },
    onclose() {
      if (!complete) throw new Error("事件连接中断");
    },
    onerror(error) {
      if (error instanceof FatalEventError || ++retries >= 5) throw error;
      return 1000;
    },
  });
}
