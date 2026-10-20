import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  FileText,
  Hotel,
  MapPin,
  Plane,
  ShieldCheck,
  Sparkles,
  Ticket,
  Users,
  X,
} from "lucide-react";
import type { Evidence, PlanOption, Resource, Run, Submit } from "../types";
import {
  dateLabel,
  orderDates,
  money,
  rangeLabel,
  requestForOption,
  bookingMessage,
  statusLabels,
  tripDestination,
  friendlyError,
} from "../lib";
import { Badge, Modal, Spinner } from "./ui";

export function Markdown({
  text,
  evidence = [],
}: {
  text: string;
  evidence?: Evidence[];
}) {
  let display = text;
  for (const [index, item] of evidence.entries())
    display = display
      .replaceAll(item.node_id, `来源 ${index + 1}`)
      .replaceAll(item.revision_id, "适用政策版本");
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {display}
      </ReactMarkdown>
    </div>
  );
}
export function Sources({ evidence }: { evidence: Evidence[] }) {
  const [open, setOpen] = useState(false);
  if (!evidence.length) return null;
  return (
    <>
      <button className="sources-button" onClick={() => setOpen(true)}>
        <BookOpen size={15} />
        <span>查看 {evidence.length} 条参考依据</span>
        <ArrowUpRight size={14} />
      </button>
      {open && (
        <Modal
          title="回答依据"
          description="以下为本次回答使用的适用条款，您可以核对原文。"
          onClose={() => setOpen(false)}
          wide
        >
          <div className="source-list">
            {evidence.map((item, index) => (
              <article className="source-item" key={item.node_id}>
                <div className="source-heading">
                  <span className="number-label">{index + 1}</span>
                  <div>
                    <strong>{item.section || "适用条款"}</strong>
                    <small>{item.source}</small>
                  </div>
                </div>
                <Markdown text={item.text} />
              </article>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
}
export function TripOptions({
  options,
  resources,
  onChoose,
  compact = false,
}: {
  options: PlanOption[];
  resources: Resource[];
  onChoose?: (option: PlanOption, index: number) => void;
  compact?: boolean;
}) {
  return (
    <div className={`trip-options ${compact ? "trip-options-compact" : ""}`}>
      {options.map((option, index) => (
        <article className="trip-option" key={option.label + index}>
          <div className="option-heading">
            <span className="option-label">
              方案 {String(index + 1).padStart(2, "0")}
            </span>
            {option.amount !== undefined && (
              <strong className="option-price">
                {money(option.amount)}
                <small> / 方案总价</small>
              </strong>
            )}
          </div>
          <h3>
            {tripDestination(option, resources)} · {option.label}
          </h3>
          <div className="meta-line">
            <CalendarDays size={14} />
            {rangeLabel(option.start, option.end)}
            {option.people && (
              <>
                <span>·</span>
                <Users size={14} />
                {option.people} 人
              </>
            )}
          </div>
          <div className="trip-resources">
            {option.resource_ids.map((id) => {
              const r = resources.find((item) => item.id === id);
              return (
                <span key={id}>
                  {r?.kind === "flight" ? (
                    <Plane size={14} />
                  ) : (
                    <Hotel size={14} />
                  )}{" "}
                  {r?.name || "已选旅行资源"}
                </span>
              );
            })}
          </div>
          {option.explanation && (
            <p className="muted option-description">{option.explanation}</p>
          )}
          {!compact && option.days && (
            <div className="itinerary-mini">
              {option.days.map((day, n) => (
                <div key={day.date}>
                  <span className="day-dot">{n + 1}</span>
                  <div>
                    <small>{dateLabel(day.date)}</small>
                    <p>{day.activity}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
          {option.scope && <p className="price-note">{option.scope}</p>}
          {option.evidence && (
            <Sources evidence={option.evidence.evidence} />
          )}{" "}
          {onChoose && (
            <button
              className="button button-primary button-full"
              onClick={() => onChoose(option, index)}
            >
              选择此方案，查看预订报价
              <ArrowRight size={16} />
            </button>
          )}
        </article>
      ))}
    </div>
  );
}
function ResourceResults({
  run,
  resources,
  submit,
}: {
  run: Run;
  resources: Resource[];
  submit: Submit;
}) {
  const [selected, setSelected] = useState<Record<string, string>>({});
  const candidates = Object.values(run.result.results || {}).flatMap(
    (item) => item.candidates || [],
  );
  return (
    <div className="search-results">
      <div className="section-heading">
        <div>
          <h3>找到这些旅行选择</h3>
          <p>按您的日期与人数查询，库存以最终确认为准。</p>
        </div>
      </div>
      <div className="resource-results-grid">
        {candidates.map((item) => (
          <button
            key={item.id}
            className={`resource-choice ${selected[item.kind] === item.id ? "is-selected" : ""}`}
            onClick={() =>
              setSelected((old) => ({
                ...old,
                [item.kind]: old[item.kind] === item.id ? "" : item.id,
              }))
            }
          >
            <span className="resource-icon">
              {item.kind === "flight" ? (
                <Plane size={21} />
              ) : (
                <Hotel size={21} />
              )}
            </span>
            <span className="resource-description">
              <strong>{item.name}</strong>
              <small>
                {item.kind === "flight"
                  ? `${run.payload.departure || "出发地"} → ${run.payload.destination || "目的地"}`
                  : "住宿 · " + (run.payload.destination || "目的地")}
              </small>
              <span>
                {money(item.amount)} <small>本次合计</small>
              </span>
            </span>
            <span className="select-dot">
              {selected[item.kind] === item.id && <Check size={12} />}
            </span>
          </button>
        ))}
      </div>
      {candidates.length === 0 ? (
        <p className="muted">当前条件下没有可选资源，试着调整日期或人数。</p>
      ) : (
        <div className="result-action-row">
          <span className="muted">
            已选 {Object.values(selected).filter(Boolean).length} 项
          </span>
          <button
            className="button button-primary"
            disabled={!Object.values(selected).some(Boolean)}
            onClick={() => {
              const ids = Object.values(selected).filter(Boolean);
              const names = ids
                .map(
                  (id) => candidates.find((item) => item.id === id)?.name || id,
                )
                .join("、");
              const text = `请预订${names}，日期 ${run.payload.start} 至 ${run.payload.end}，${run.payload.people || 1} 人。请核对报价。`;
              return submit(text, {
                ...run.payload,
                intent: "book",
                question: text,
                resource_ids: ids,
              });
            }}
          >
            查看预订报价
            <ArrowRight size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
const actionTitles: Record<string, string> = {
  book: "确认预订",
  change: "确认订单变更",
  cancel: "确认取消预订",
  plan_create: "保存旅行方案",
  case_create: "提交人工服务申请",
  case_message: "向客服补充说明",
  repair_save: "保存行程调整方案",
  admin_write: "确认管理操作",
};
export function ApprovalCard({
  run,
  resources,
  onDecision,
  onRenew,
  busy,
}: {
  run: Run;
  resources: Resource[];
  onDecision: (run: Run, decision: "approve" | "reject") => void;
  onRenew: (run: Run) => void;
  busy: boolean;
}) {
  const proposal = run.result.approval?.proposal;
  const [expanded, setExpanded] = useState(false);
  if (!proposal) return null;
  const expired = Date.now() / 1000 > proposal.expires;
  const invalid = proposal.actions.some(
    (a, i) =>
      ["book", "change", "cancel"].includes(a.kind) && !run.preview?.[i]?.valid,
  );
  const first = proposal.actions[0]?.kind;
  return (
    <article className="approval-card">
      <div className="approval-banner">
        <span className="approval-icon">
          <ShieldCheck size={23} />
        </span>
        <div>
          <span className="eyebrow">由您做最后决定</span>
          <h3>{actionTitles[first] || "请核对本次操作"}</h3>
        </div>
        <Badge status="WAITING" />
      </div>
      <div className="approval-content">
        {proposal.actions.map((action, index) => {
          const preview = run.preview?.[index];
          const data = action.data;
          return (
            <div className="approval-action" key={index}>
              {["book", "change", "cancel"].includes(action.kind) ? (
                <>
                  <div className="approval-resource">
                    <span className="resource-icon">
                      {preview?.resource_kind === "flight" ? (
                        <Plane size={21} />
                      ) : (
                        <Hotel size={21} />
                      )}
                    </span>
                    <div>
                      <strong>{preview?.name || "正在获取报价详情"}</strong>
                      <p>
                        {action.kind === "cancel"
                          ? "取消这项预订"
                          : action.kind === "change"
                            ? "变更为这项预订"
                            : "新增这项预订"}
                      </p>
                    </div>
                    <strong>
                      {preview ? money(preview.amount) : "待核实"}
                    </strong>
                  </div>
                  {preview && (
                    <div className="detail-grid">
                      <div>
                        <span>数量</span>
                        <strong>
                          {preview.quantity}{" "}
                          {preview.resource_kind === "flight"
                            ? "位旅客"
                            : "间客房"}
                        </strong>
                      </div>
                      <div>
                        <span>出行日期</span>
                        <strong>
                          {preview.resource_kind === "flight"
                            ? dateLabel(preview.details?.date)
                            : rangeLabel(
                                orderDates(preview.slots || []).start,
                                orderDates(preview.slots || []).end,
                              )}
                        </strong>
                      </div>
                      {preview.fee !== undefined && preview.fee !== null && (
                        <div>
                          <span>本次取消费</span>
                          <strong>{money(preview.fee)}</strong>
                        </div>
                      )}
                      {preview.difference !== undefined &&
                        preview.difference !== null && (
                          <div>
                            <span>订单金额差额</span>
                            <strong>
                              {preview.difference >= 0 ? "+" : "−"}
                              {money(Math.abs(preview.difference))}
                            </strong>
                          </div>
                        )}
                    </div>
                  )}
                </>
              ) : action.kind === "plan_create" ? (
                <>
                  <p className="approval-description">
                    确认后，以下方案会保存到「我的行程」。保存方案不会自动预订。
                  </p>
                  <TripOptions
                    options={data.options}
                    resources={resources}
                    compact
                  />
                </>
              ) : action.kind === "repair_save" ? (
                <>
                  <p className="approval-description">
                    确认保存新的调整报告。原行程和已有订单不会自动变更。
                  </p>
                  <TripOptions
                    options={data.report.options}
                    resources={resources}
                    compact
                  />
                  {data.report.unresolved?.length > 0 && (
                    <div className="notice notice-warm">
                      <CircleAlert size={17} />
                      <div>
                        <strong>仍需核实</strong>
                        {data.report.unresolved.map((text: string) => (
                          <p key={text}>{text}</p>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : ["case_create", "case_message"].includes(action.kind) ? (
                <>
                  <div className="approval-document">
                    <FileText size={21} />
                    <div>
                      <strong>您的服务申请</strong>
                      <p>{data.request?.question || "旅行服务咨询"}</p>
                    </div>
                  </div>
                  <p className="muted">
                    确认后会向人工客服共享本次说明与相关会话，便于接续处理。
                  </p>
                  {data.customer?.answer && (
                    <details>
                      <summary>查看附带的客服说明</summary>
                      <Markdown text={data.customer.answer} />
                    </details>
                  )}
                </>
              ) : action.kind === "admin_write" ? (
                <AdminAction data={data} subject={preview?.subject} />
              ) : (
                <p>该操作暂不支持在线确认，请联系管理员。</p>
              )}
            </div>
          );
        })}
        {proposal.evidence?.length > 0 && (
          <Sources evidence={proposal.evidence} />
        )}
        <div className="approval-assurance">
          <ShieldCheck size={15} />
          <span>只有您确认后，操作才会执行。</span>
        </div>
        {(expired || invalid) && (
          <div className="notice notice-warm">
            <Clock3 size={16} />
            <span>
              {expired
                ? "本次确认已过期，请拒绝后重新发起需求。"
                : "报价或订单已变化，请拒绝后重新获取方案。"}
            </span>
          </div>
        )}
        <div className="approval-buttons">
          {(expired || invalid) && (
            <button
              className="button button-primary"
              disabled={busy}
              onClick={() => onRenew(run)}
            >
              重新获取并核对
            </button>
          )}
          <button
            className="button button-primary"
            disabled={busy || expired || invalid || !actionTitles[first]}
            onClick={() => onDecision(run, "approve")}
          >
            {busy ? (
              <Spinner label="处理中" />
            ) : (
              <>
                <Check size={16} />
                {first === "plan_create" || first === "repair_save"
                  ? "确认并保存"
                  : "确认执行"}
              </>
            )}
          </button>
          <button
            className="button button-secondary"
            disabled={busy}
            onClick={() => onDecision(run, "reject")}
          >
            暂不执行
          </button>
          <button
            className="text-button approval-more"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "收起" : "有效时间"}
            <ChevronDown size={13} />
          </button>
        </div>
        {expanded && (
          <p className="muted tiny">
            请在 {new Date(proposal.expires * 1000).toLocaleString("zh-CN")}{" "}
            前确认。修改需求时，请先选择「暂不执行」，再重新提交。
          </p>
        )}
      </div>
    </article>
  );
}
function AdminAction({ data, subject }: { data: any; subject?: string }) {
  const names: Record<string, string> = {
    case_claim: "领取工单",
    case_reply: data.close ? "回复并关闭工单" : "回复工单",
    knowledge_import: "导入知识文档",
    knowledge_publish: "发布知识版本",
    knowledge_revoke: "撤回知识版本",
    knowledge_rollback: "恢复历史知识版本",
  };
  return (
    <div className="admin-action-preview">
      <div className="approval-document">
        <FileText size={22} />
        <div>
          <strong>{names[data.kind] || "管理操作"}</strong>
          {data.name && <p>{data.name}</p>}
          {subject && <p>{subject}</p>}
        </div>
      </div>
      {data.text && (
        <div className="reply-preview">
          <Markdown text={data.text} />
        </div>
      )}
      {data.metadata && (
        <div className="detail-grid">
          <div>
            <span>文档</span>
            <strong>{data.metadata.document}</strong>
          </div>
          <div>
            <span>供应商 / 产品</span>
            <strong>
              {data.metadata.supplier} / {data.metadata.product}
            </strong>
          </div>
          <div>
            <span>生效日期</span>
            <strong>{data.metadata.valid_from}</strong>
          </div>
          <div>
            <span>截止日期</span>
            <strong>{data.metadata.valid_to}</strong>
          </div>
          <div>
            <span>配置的取消费</span>
            <strong>{money(data.metadata.rules?.cancel_fee_cents)}</strong>
          </div>
        </div>
      )}
      {data.kind === "knowledge_revoke" && (
        <p className="muted">
          撤回后，该版本不再用于业务回答和交易核验。历史记录仍然保留。
        </p>
      )}
      {data.kind === "knowledge_rollback" && (
        <p className="muted">
          将恢复目标版本，同时撤回受影响的后续版本。请确认已核对适用日期。
        </p>
      )}
    </div>
  );
}
function RunContent({
  run,
  resources,
  submit,
  onDecision,
  busy,
  stage,
  onStop,
  onRenew,
  onSupport,
}: {
  run: Run;
  resources: Resource[];
  submit: Submit;
  onDecision: (r: Run, d: "approve" | "reject") => void;
  busy: boolean;
  stage?: string;
  onStop: (r: Run) => void;
  onRenew: (r: Run) => void;
  onSupport: () => void;
}) {
  const evidence = run.result.evidence?.evidence || [];
  if (run.status === "WAITING")
    return (
      <ApprovalCard
        run={run}
        resources={resources}
        onDecision={onDecision}
        onRenew={onRenew}
        busy={busy}
      />
    );
  if (run.status === "RUNNING" || run.status === "QUEUED")
    return (
      <div className="run-progress">
        <div className="thinking-orbit">
          <span />
          <span />
          <span />
        </div>
        <div>
          <strong>
            {run.cancel_requested
              ? "已请求停止，正在收尾"
              : run.status === "QUEUED"
                ? "需求已收到，马上为您安排"
                : stage || "旅行助手正在为您处理"}
          </strong>
          <p>
            {run.cancel_requested
              ? "当前模型调用结束后停止后续步骤，已完成的业务会保留。您可以先浏览其他页面。"
              : run.status === "QUEUED"
                ? "排队期间您可以浏览其他页面，结果会保留。"
                : "正在核对资源与适用条件，请稍候。"}
          </p>
        </div>
        <button
          className="text-button"
          disabled={busy || run.cancel_requested}
          onClick={() => onStop(run)}
        >
          {run.cancel_requested ? "正在停止" : "停止"}
        </button>
      </div>
    );
  if (run.status === "FAILED")
    return (
      <div className="failed-result">
        <CircleAlert size={21} />
        <div>
          <strong>这次没能处理完成</strong>
          <p>{friendlyError(run.error || "请调整需求后重试。")}</p>
          <div className="inline-actions">
            <button
              className="button button-secondary"
              onClick={() => onRenew(run)}
            >
              重新尝试
            </button>
            <button className="text-button" onClick={onSupport}>
              联系人工客服
              <ArrowUpRight size={13} />
            </button>
          </div>
        </div>
      </div>
    );
  if (run.status === "CANCELLED")
    return (
      <div className="notice">
        <X size={17} />
        <span>已停止本次处理。已完成的预订不会因此自动取消。</span>
      </div>
    );
  if (run.result.decision === "reject")
    return (
      <div className="notice">
        <CheckCircle2 size={18} />
        <span>
          已按您的决定结束，未执行提案中的操作。您可以调整需求后再告诉我。
        </span>
      </div>
    );
  return (
    <div className="run-content">
      {run.result.customer?.answer && (
        <Markdown text={run.result.customer.answer} evidence={evidence} />
      )}{" "}
      {run.result.evidence?.status === "INSUFFICIENT" &&
        !run.result.customer && (
          <p>暂时没有找到足够的适用条款，建议联系人工客服核实。</p>
        )}
      {evidence.length > 0 && <Sources evidence={evidence} />}{" "}
      {run.result.results && (
        <ResourceResults run={run} resources={resources} submit={submit} />
      )}{" "}
      {run.result.plan && (
        <>
          <div className="success-heading">
            <CheckCircle2 size={19} />
            <strong>旅行方案已保存</strong>
          </div>
          <p className="muted">可以继续比较方案，选择后再确认预订。</p>
          <TripOptions
            options={run.result.plan.options}
            resources={resources}
            onChoose={(option, index) =>
              submit(bookingMessage(option, index, resources), {
                ...requestForOption(option),
                option_id: option.option_id,
              })
            }
          />
        </>
      )}
      {run.result.repair && (
        <>
          <div className="success-heading">
            <CheckCircle2 size={19} />
            <strong>行程调整报告已保存</strong>
          </div>
          <TripOptions
            options={run.result.repair.options}
            resources={resources}
            onChoose={(option, index) =>
              submit(bookingMessage(option, index, resources), {
                ...requestForOption({ ...option, people: run.payload.people }),
                option_id: option.option_id,
              })
            }
          />
          {run.result.repair.unresolved?.length > 0 && (
            <div className="notice notice-warm">
              <CircleAlert size={17} />
              <div>
                <strong>出发前还需核实</strong>
                {run.result.repair.unresolved.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            </div>
          )}
          <p className="muted tiny">
            替代资源需另行确认预订，已有订单不会自动取消或改签。
          </p>
        </>
      )}
      {run.result.case_id && (
        <div className="success-block">
          <span className="success-icon">
            <CheckCircle2 size={23} />
          </span>
          <div>
            <strong>
              {run.payload.intent === "admin_write"
                ? "服务处理已更新"
                : run.payload.case_id
                  ? "补充说明已发送"
                  : "服务申请已提交"}
            </strong>
            <p>您可以在「服务中心」查看进度与客服回复。</p>
          </div>
        </div>
      )}
      {run.result.knowledge && (
        <div className="success-block">
          <CheckCircle2 size={22} />
          <div>
            <strong>知识管理操作已完成</strong>
            <p>请在知识管理中查看最新版本状态。</p>
          </div>
        </div>
      )}
      {run.result.operations &&
        !run.result.plan &&
        !run.result.repair &&
        !run.result.case_id &&
        !run.result.knowledge && (
          <div className="operation-results">
            {run.result.operations.map((op, i) => (
              <div
                className={`operation-result ${op.status === "SUCCESS" ? "" : "operation-failed"}`}
                key={i}
              >
                {op.status === "SUCCESS" ? (
                  <CheckCircle2 size={21} />
                ) : (
                  <CircleAlert size={21} />
                )}
                <div>
                  <strong>
                    {op.status === "SUCCESS"
                      ? run.payload.intent === "cancel"
                        ? "预订已取消"
                        : run.payload.intent === "change"
                          ? "订单已更新"
                          : "预订已确认"
                      : "这项操作未完成"}
                  </strong>
                  {op.amount !== undefined && (
                    <p>订单金额 {money(op.amount)}</p>
                  )}
                  {op.fee !== undefined && <p>本次取消费 {money(op.fee)}</p>}
                  {op.message && <p>{friendlyError(op.message)}</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      {run.result.message && <Markdown text={run.result.message} />}
      {run.result.policy_choices && (
        <div className="inline-actions">
          {run.result.policy_choices.map((resource) => (
            <button
              key={resource.id}
              className="button button-secondary"
              onClick={() =>
                submit(
                  `请查询${resource.name}：${run.payload.resolved_question || run.payload.question}`,
                  {
                    ...run.payload,
                    intent: "policy",
                    resource_ids: [resource.id],
                  },
                )
              }
            >
              {resource.name}的政策
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function RunCard(props: Parameters<typeof RunContent>[0]) {
  const steps = props.run.activity || [];
  return (
    <>
      {steps.length > 0 && (
        <details className="processing-details">
          <summary>
            <Sparkles size={14} />
            <span>处理过程</span>
            <small>{steps.length} 个已完成步骤</small>
            <ChevronDown size={13} />
          </summary>
          <ol>
            {steps.map((step) => (
              <li key={step.id}>
                <CheckCircle2 size={14} />
                <div>
                  <strong>{step.label}</strong>
                  {step.tools.map((tool, i) => (
                    <span key={i}>
                      {tool.label} · {tool.count} 次
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
          <p>展示实际执行步骤与工具调用摘要。</p>
        </details>
      )}
      <RunContent {...props} />
    </>
  );
}
