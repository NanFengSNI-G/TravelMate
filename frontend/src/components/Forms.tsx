import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  CalendarDays,
  Check,
  FileText,
  Hotel,
  Plane,
  ShieldCheck,
  UploadCloud,
  X,
} from "lucide-react";
import type { Order, Plan, Resource, Submit } from "../types";
import {
  addDays,
  dateLabel,
  friendlyError,
  money,
  nights,
  orderDates,
  rangeLabel,
  tripDestination,
} from "../lib";
import { Modal, Spinner } from "./ui";

export function TripForm({
  mode = "plan",
  resources,
  submit,
  onClose,
  plan,
  order,
}: {
  mode?: "plan" | "search" | "repair" | "change";
  resources: Resource[];
  submit: Submit;
  onClose: () => void;
  plan?: Plan;
  order?: Order;
}) {
  const original = resources.find((r) => r.id === order?.resource);
  const planFlight = resources.find(
    (r) => r.kind === "flight" && plan?.options[0]?.resource_ids.includes(r.id),
  );
  const allCandidates = resources.filter((r) => r.kind === original?.kind);
  const today = new Date().toLocaleDateString("en-CA");
  const dates = [
    ...new Set(
      resources
        .filter(
          (r) =>
            r.kind === "flight" && r.details.date && r.details.date >= today,
        )
        .map((r) => r.details.date!),
    ),
  ].sort();
  const alternative = allCandidates.find(
    (r) =>
      r.id !== original?.id &&
      r.details.destination === original?.details.destination &&
      (r.kind !== "flight" ||
        (r.details.departure === original?.details.departure &&
          r.details.date! >= original?.details.date!)),
  );
  const previousDates = orderDates(order?.slots || [], original);
  const initial =
    mode === "change" && original
      ? alternative?.details.date || previousDates.start
      : plan?.options[0]?.start || dates[0];
  const [start, setStart] = useState(initial || "");
  const [end, setEnd] = useState(
    mode === "change" && original?.kind === "hotel"
      ? previousDates.end || ""
      : plan?.options[0]?.end || (initial ? addDays(initial, 3) : ""),
  );
  const [people, setPeople] = useState(
    (order
      ? Math.min(
          6,
          order.quantity *
            (original?.kind === "hotel" ? original.details.max_people || 1 : 1),
        )
      : plan?.options[0]?.people) || 1,
  );
  const [budget, setBudget] = useState(
    (plan?.options[0]?.budget_cents || 600000) / 100,
  );
  const [destination, setDestination] = useState(
    plan
      ? tripDestination(plan.options[0], resources)
      : original?.details.destination ||
          resources[0]?.details.destination ||
          "",
  );
  const [departure, setDeparture] = useState(
    original?.details.departure ||
      resources.find((r) => r.kind === "flight")?.details.departure ||
      "北京",
  );
  const candidates = allCandidates.filter(
    (r) =>
      r.details.destination === destination &&
      (r.kind !== "flight" ||
        (r.details.departure === departure && r.details.date === start)),
  );
  const [replacement, setReplacement] = useState(
    alternative?.id || original?.id || "",
  );
  useEffect(() => {
    if (mode === "change" && !candidates.some((r) => r.id === replacement)) {
      setReplacement(
        candidates.find((r) => r.id !== original?.id)?.id ||
          candidates[0]?.id ||
          "",
      );
    }
  }, [mode, start, destination, departure, replacement, resources]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const titles = {
    plan: "规划一段新的旅程",
    search: "查找航班与住宿",
    repair: "调整已有行程",
    change: "变更这项预订",
  };
  async function send(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!start || !end || nights(start, end) < 1 || nights(start, end) > 14) {
      setError("请选择有效日期，住宿时长为 1 至 14 晚。");
      return;
    }
    if (
      departure === destination &&
      (mode === "plan" || mode === "repair" || original?.kind === "flight")
    ) {
      setError("出发城市与目的地不能相同。");
      return;
    }
    if (mode === "change" && !replacement) {
      setError("请选择替代资源。");
      return;
    }
    setBusy(true);
    const text =
      mode === "repair"
        ? `请调整我的${destination}行程，日期改为${start}至${end}，${people}人，预算${budget}元。`
        : mode === "change"
          ? `请将${original?.name || "这项预订"}变更为${resources.find((r) => r.id === replacement)?.name || "所选资源"}，日期为${start}至${end}，${people}位旅客。`
          : `${mode === "search" ? "查询" : "规划"}从${departure}前往${destination}的旅行，${start}至${end}，${people}人，预算${budget}元。`;
    const ok = await submit(text, {
      intent: mode,
      question: text,
      departure,
      destination,
      start,
      end,
      people,
      budget_cents: Math.round(budget * 100),
      ...(plan ? { plan_id: plan.id } : {}),
      ...(order ? { order_id: order.id, resource_ids: [replacement] } : {}),
    });
    setBusy(false);
    if (ok) onClose();
  }
  return (
    <Modal
      title={titles[mode]}
      description={
        mode === "repair"
          ? "告诉我们新的安排，旅行助手会研究两套替代方案。"
          : "先确定出行条件，我们会根据可用资源为您安排。"
      }
      onClose={onClose}
    >
      <form onSubmit={send} className="product-form">
        {order && (
          <div className="form-context">
            <Plane size={18} />
            <div>
              <strong>{original?.name || "当前预订"}</strong>
              <small>原订单金额 {money(order.amount)}</small>
            </div>
          </div>
        )}
        {mode === "change" && (
          <label>
            选择替代资源
            <select
              value={replacement}
              onChange={(e) => {
                setReplacement(e.target.value);
                const resource = candidates.find(
                  (r) => r.id === e.target.value,
                );
                if (resource?.details.date) {
                  setStart(resource.details.date);
                  setEnd(
                    addDays(
                      resource.details.date,
                      Math.max(nights(start, end) || 3, 1),
                    ),
                  );
                }
              }}
            >
              {candidates.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ·{" "}
                  {r.details.date ? dateLabel(r.details.date) : "酒店房型"} ·{" "}
                  {money(r.price)} 起
                </option>
              ))}
            </select>
          </label>
        )}
        {(mode !== "change" || original?.kind === "flight") && (
          <label>
            出发城市
            <select
              value={departure}
              onChange={(e) => setDeparture(e.target.value)}
            >
              {[
                ...new Set(
                  resources
                    .filter((r) => r.kind === "flight")
                    .map((r) => r.details.departure)
                    .filter(Boolean),
                ),
              ]
                .sort()
                .map((city) => (
                  <option key={city}>{city}</option>
                ))}
            </select>
          </label>
        )}
        <label>
          目的地
          <select
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
          >
            {[
              ...new Set(
                resources.map((r) => r.details.destination).filter(Boolean),
              ),
            ].map((city) => (
              <option key={city}>{city}</option>
            ))}
          </select>
        </label>
        <div className="form-grid">
          <label>
            出发 / 入住日期
            <input
              required
              type="date"
              value={start}
              onChange={(e) => {
                setStart(e.target.value);
                if (!end || e.target.value >= end)
                  setEnd(addDays(e.target.value, 3));
              }}
            />
          </label>
          <label>
            行程结束 / 退房日期
            <input
              required
              type="date"
              value={end}
              min={start ? addDays(start, 1) : undefined}
              max={start ? addDays(start, 14) : undefined}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
        </div>
        {dates.length > 0 && (
          <p className="field-hint">
            <CalendarDays size={13} />
            当前航班出发日期：{dateLabel(dates[0])} 至{" "}
            {dateLabel(dates[dates.length - 1])}（{dates.length} 个可选日期）
          </p>
        )}
        <div className="form-grid">
          <label>
            出行人数
            <select
              value={people}
              onChange={(e) => setPeople(Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n} 人
                </option>
              ))}
            </select>
          </label>
          <label>
            机票与住宿预算（元）
            <input
              required
              type="number"
              min="1"
              step="1"
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
            />
          </label>
        </div>
        {mode === "change" && original?.kind === "hotel" && (
          <p className="field-hint">
            原订单记录了 {order?.quantity}{" "}
            间客房，未记录入住人数。默认按原房型满住推算，请核对人数与报价中的房间数。
          </p>
        )}
        <div className="notice">
          <ShieldCheck size={17} />
          <span>方案或变更会先交给您核对。未经确认，不会保存或预订。</span>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-footer">
          <button
            type="button"
            className="button button-secondary"
            onClick={onClose}
          >
            暂不安排
          </button>
          <button
            type="submit"
            disabled={busy || !resources.length}
            className="button button-primary"
          >
            {busy ? (
              <Spinner label="提交中" />
            ) : (
              <>
                {mode === "search"
                  ? "查找资源"
                  : mode === "change"
                    ? "获取变更报价"
                    : "开始规划"}
                <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function SupportForm({
  orders,
  resources,
  submit,
  onClose,
}: {
  orders: Order[];
  resources: Resource[];
  submit: Submit;
  onClose: () => void;
}) {
  const [topic, setTopic] = useState("订单与费用");
  const [text, setText] = useState("");
  const [orderId, setOrderId] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="联系人工客服"
      description="请描述您需要帮助的事情，我们会把相关信息交给客服接续处理。"
      onClose={onClose}
    >
      <form
        className="product-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          const question = `${topic}：${text.trim()}`;
          const ok = await submit(question, {
            intent: "support",
            question,
            ...(orderId ? { order_id: orderId } : {}),
          });
          setBusy(false);
          if (ok) onClose();
        }}
      >
        <label>
          需要哪方面帮助？
          <select value={topic} onChange={(e) => setTopic(e.target.value)}>
            {[
              "订单与费用",
              "改签与取消",
              "行程调整",
              "政策说明",
              "其他问题",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          关联预订（可选）
          <select value={orderId} onChange={(e) => setOrderId(e.target.value)}>
            <option value="">不关联预订</option>
            {orders.map((order) => (
              <option key={order.id} value={order.id}>
                {resources.find((r) => r.id === order.resource)?.name ||
                  "旅行预订"}{" "}
                · {money(order.amount)}
              </option>
            ))}
          </select>
        </label>
        <label>
          详细说明
          <textarea
            required
            rows={5}
            maxLength={1600}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="例如：我想了解这次改签的费用明细，希望客服帮我核实。"
          />
        </label>
        <p className="field-hint">
          提交后会先展示待确认内容，由您决定是否创建服务申请。
        </p>
        <div className="modal-footer">
          <button
            type="button"
            className="button button-secondary"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="button button-primary"
            disabled={busy || !text.trim()}
          >
            {busy ? (
              <Spinner label="提交中" />
            ) : (
              <>
                继续并核对申请
                <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function KnowledgeForm({
  resources,
  onSubmit,
  onClose,
}: {
  resources: Resource[];
  onSubmit: (path: string, body: unknown) => Promise<boolean>;
  onClose: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [name, setName] = useState("");
  const [supplier, setSupplier] = useState(
    resources.find((r) => r.kind === "hotel")?.supplier || "",
  );
  const [product, setProduct] = useState(
    resources.find((r) => r.kind === "hotel")?.product || "",
  );
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [fee, setFee] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function choose(next?: File) {
    if (!next) return;
    if (!/\.(md|pdf)$/i.test(next.name) || next.size > 5000000) {
      setError("请选择不超过 5 MB 的 Markdown 或 PDF 文件。");
      return;
    }
    setError("");
    setFile(next);
    setMarkdown("");
    if (!name) setName(next.name.replace(/\.[^.]+$/, ""));
  }
  async function send(e: React.FormEvent) {
    e.preventDefault();
    const document =
      file ||
      (markdown.trim()
        ? new File([markdown], "pasted-policy.md", { type: "text/markdown" })
        : null);
    if (!document) return;
    setError("");
    if (start > end) {
      setError("截止日期不能早于生效日期。");
      return;
    }
    setBusy(true);
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("文件读取失败，请重新选择。"));
        reader.readAsDataURL(document);
      });
      const ok = await onSubmit("/api/knowledge/import", {
        name: document.name,
        content_base64: base64,
        metadata: {
          document: name.trim(),
          supplier: supplier.trim(),
          product: product.trim(),
          valid_from: start,
          valid_to: end,
          rules: { cancel_fee_cents: Math.round(fee * 100) },
        },
      });
      if (ok) onClose();
    } catch (error) {
      setError(friendlyError(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="导入知识文档"
      description="先核对适用范围，再确认导入。导入完成后还需单独发布。"
      onClose={onClose}
    >
      <form className="product-form" onSubmit={send}>
        <input
          ref={input}
          type="file"
          hidden
          accept=".md,.pdf"
          onChange={(e) => choose(e.target.files?.[0])}
        />
        <button
          type="button"
          className={`upload-zone ${file ? "has-file" : ""}`}
          onClick={() => input.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            choose(e.dataTransfer.files[0]);
          }}
        >
          {file ? <FileText size={29} /> : <UploadCloud size={30} />}
          <strong>{file ? file.name : "点击上传，或将文件拖到这里"}</strong>
          <small>
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · 点击重新选择`
              : "支持 Markdown、文本型 PDF，最大 5 MB"}
          </small>
        </button>
        <label>
          或粘贴 Markdown 正文
          <textarea
            rows={6}
            value={markdown}
            maxLength={100000}
            onChange={(e) => {
              setMarkdown(e.target.value);
              setFile(null);
            }}
            placeholder="适合直接录入政策文本；与上传文件二选一。标题使用 Markdown 的 #、##。"
          />
        </label>
        <label>
          文档名称 / 版本分组
          <input
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：标准房取消政策"
          />
        </label>
        <div className="form-grid">
          <label>
            供应商
            <input
              required
              value={supplier}
              onChange={(e) => setSupplier(e.target.value)}
              placeholder="与业务资源的供应商一致"
            />
          </label>
          <label>
            适用产品
            <input
              required
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              placeholder="例如 standard"
            />
          </label>
        </div>
        <div className="form-grid">
          <label>
            生效日期
            <input
              type="date"
              required
              value={start}
              onInput={(e) => setStart(e.currentTarget.value)}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            截止日期
            <input
              type="date"
              required
              value={end}
              onInput={(e) => setEnd(e.currentTarget.value)}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
        </div>
        <label>
          配置的取消费（元）
          <input
            type="number"
            min="0"
            step="0.01"
            required
            value={fee}
            onChange={(e) => setFee(Number(e.target.value))}
          />
        </label>
        <p className="field-hint">
          新条款请使用合理的新生效日期。业务规则需要人工核对，不从文档中自动猜测。
        </p>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="modal-footer">
          <button
            type="button"
            className="button button-secondary"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="button button-primary"
            disabled={(!file && !markdown.trim()) || busy}
          >
            {busy ? (
              <Spinner label="正在上传" />
            ) : (
              <>
                核对导入内容
                <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
