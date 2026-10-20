import { useState } from "react";
import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  Check,
  ChevronRight,
  CircleAlert,
  Compass,
  FileText,
  Headphones,
  Hotel,
  Inbox,
  Luggage,
  MapPin,
  MessageCircle,
  MoreHorizontal,
  Plane,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Ticket,
  UploadCloud,
  Users,
} from "lucide-react";
import type {
  Case,
  Order,
  Page,
  Plan,
  PlanOption,
  Resource,
  Revision,
  Run,
  Submit,
  User,
} from "../types";
import {
  dateLabel,
  intentLabels,
  money,
  orderDates,
  rangeLabel,
  requestForOption,
  bookingMessage,
  tripDestination,
} from "../lib";
import { Badge, Empty, Modal, PageHeader, Spinner } from "./ui";
import { Markdown, TripOptions } from "./Results";

export function Home({
  user,
  plans,
  orders,
  runs,
  resources,
  navigate,
  onPlan,
  onSearch,
  onSupport,
  onOpenPlan,
  submit,
}: {
  user: User;
  plans: Plan[];
  orders: Order[];
  runs: Run[];
  resources: Resource[];
  navigate: (page: Page) => void;
  onPlan: () => void;
  onSearch: () => void;
  onSupport: () => void;
  onOpenPlan: (p: Plan) => void;
  submit: Submit;
}) {
  const greeting =
    new Date().getHours() < 12
      ? "早上好"
      : new Date().getHours() < 18
        ? "下午好"
        : "晚上好";
  const waiting = runs.filter((r) => r.status === "WAITING");
  const confirmed = orders.filter((o) => o.status === "CONFIRMED");
  const flightDates = [
    ...new Set(
      resources
        .filter((r) => r.kind === "flight")
        .map((r) => r.details.date)
        .filter(Boolean),
    ),
  ];
  return (
    <div className="page dashboard">
      <PageHeader
        eyebrow="YOUR TRAVEL WORKSPACE"
        title={`${greeting}，${user.name}`}
        text="把时间留给期待，把安排交给我们。"
      >
        <button className="button button-secondary" onClick={onSearch}>
          <Search size={16} />
          查找旅行资源
        </button>
      </PageHeader>
      <section className="travel-hero">
        <div className="hero-photo" />
        <div className="hero-content">
          <span className="hero-kicker">
            <span /> 下一段旅程，从这里开始
          </span>
          <h2>
            世界很大，
            <br />
            下一程更从容。
          </h2>
          <p>
            从一个想法到一份行程，
            <br />
            您的旅行助手，始终在身边。
          </p>
          <button className="button button-white" onClick={onPlan}>
            规划我的旅行
            <ArrowUpRight size={17} />
          </button>
        </div>
        <div className="hero-location">
          <span>
            <MapPin size={14} />
            中国 · 上海
          </span>
          <small>城市的另一面，等你发现</small>
        </div>
      </section>
      <div className="overview-grid">
        <button className="overview-card" onClick={() => navigate("plans")}>
          <span className="stat-icon">
            <Luggage size={21} />
          </span>
          <div>
            <span>已保存行程</span>
            <strong>
              {plans.length}
              <small>段旅程</small>
            </strong>
          </div>
          <ArrowUpRight size={17} />
        </button>
        <button className="overview-card" onClick={() => navigate("orders")}>
          <span className="stat-icon stat-blue">
            <Ticket size={21} />
          </span>
          <div>
            <span>有效预订</span>
            <strong>
              {confirmed.length}
              <small>项安排</small>
            </strong>
          </div>
          <ArrowUpRight size={17} />
        </button>
        <button className="overview-card" onClick={() => navigate("assistant")}>
          <span className="stat-icon stat-amber">
            <ShieldCheck size={21} />
          </span>
          <div>
            <span>等待我的确认</span>
            <strong>
              {waiting.length}
              <small>项待办</small>
            </strong>
          </div>
          <ArrowUpRight size={17} />
        </button>
      </div>
      <div className="dashboard-columns">
        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">YOUR NEXT CHAPTER</span>
              <h2>我的旅行计划</h2>
            </div>
            <button className="text-button" onClick={() => navigate("plans")}>
              全部行程
              <ArrowRight size={15} />
            </button>
          </div>
          {plans.length ? (
            <div className="home-plans">
              {plans.slice(0, 2).map((plan) => (
                <button
                  className="home-plan"
                  key={plan.id}
                  onClick={() => onOpenPlan(plan)}
                >
                  <div className="home-plan-image">
                    <MapPin size={18} />
                  </div>
                  <div>
                    <strong>
                      {tripDestination(plan.options[0], resources)} ·{" "}
                      {plan.options[0].label}
                    </strong>
                    <span>
                      {rangeLabel(plan.options[0].start, plan.options[0].end)}
                    </span>
                  </div>
                  <ChevronRight size={17} />
                </button>
              ))}
            </div>
          ) : (
            <div className="first-trip-empty">
              <span className="route-illustration">
                <MapPin size={22} />
                <i />
                <Plane size={24} />
              </span>
              <h3>每段好旅程，都从一个想法开始</h3>
              <p>告诉我们想去哪里，行程、住宿与交通一起安排。</p>
            </div>
          )}
        </section>
        <section className="panel assistant-promo">
          <div className="promo-icon">
            <Sparkles size={22} />
          </div>
          <span className="eyebrow">ALWAYS BY YOUR SIDE</span>
          <h2>旅行的事，随时问我</h2>
          <p>
            想知道取消条件，或是临时调整安排？
            <br />
            从一个问题开始，让旅程少一点不确定。
          </p>
          <div className="question-chips">
            <button
              onClick={() =>
                submit(
                  "请帮我解释标准房的取消费用与适用条件。",
                  {
                    intent: "policy",
                    question: "标准房的取消费用与适用条件是什么？",
                    resource_ids: resources
                      .filter((r) => r.kind === "hotel")
                      .slice(0, 1)
                      .map((r) => r.id),
                  },
                  true,
                )
              }
            >
              酒店取消需要哪些费用？
              <ArrowUpRight size={14} />
            </button>
            <button onClick={() => navigate("assistant")}>
              我想调整一下出行计划
              <ArrowUpRight size={14} />
            </button>
          </div>
        </section>
      </div>
      <section className="destination-strip">
        <div>
          <MapPin size={19} />
          <strong>
            当前可选目的地 ·{" "}
            {[
              ...new Set(
                resources.map((r) => r.details.destination).filter(Boolean),
              ),
            ]
              .slice(0, 6)
              .join("、") || "正在加载"}
            {new Set(
              resources.map((r) => r.details.destination).filter(Boolean),
            ).size > 6 &&
              ` 等 ${new Set(resources.map((r) => r.details.destination).filter(Boolean)).size} 个城市`}
          </strong>
          <span>
            {flightDates.length
              ? `航班可选 ${dateLabel([...flightDates].sort()[0])} 至 ${dateLabel([...flightDates].sort().at(-1))}，共 ${flightDates.length} 个日期`
              : "查看资源以了解可用日期"}
          </span>
        </div>
      </section>
    </div>
  );
}
export function PlansPage({
  plans,
  resources,
  onPlan,
  onOpenPlan,
}: {
  plans: Plan[];
  resources: Resource[];
  onPlan: () => void;
  onOpenPlan: (p: Plan) => void;
}) {
  const [query, setQuery] = useState("");
  const filtered = plans.filter((p) =>
    `${tripDestination(p.options[0], resources)} ${p.options.map((o) => o.label).join(" ")}`.includes(
      query,
    ),
  );
  return (
    <div className="page">
      <PageHeader
        eyebrow="EVERY JOURNEY, TOGETHER"
        title="我的行程"
        text="保存每一次期待，也从容应对每一次变化。"
      >
        <button className="button button-primary" onClick={onPlan}>
          <Plus size={16} />
          规划新行程
        </button>
      </PageHeader>
      <div className="page-toolbar">
        <div className="filter-tabs">
          <button className="active">
            全部行程<span>{plans.length}</span>
          </button>
        </div>
        <label className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索行程"
            placeholder="搜索目的地或方案"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      {!plans.length ? (
        <div className="panel">
          <Empty
            icon={<Luggage size={30} />}
            title="把下一程放进计划里"
            text="与旅行助手一起规划，确认保存后，所有方案都会收在这里。"
            action="开始规划"
            onAction={onPlan}
          />
        </div>
      ) : !filtered.length ? (
        <Empty
          icon={<Search size={27} />}
          title="没有找到对应行程"
          text="换个关键词，或查看全部行程。"
          action="清除搜索"
          onAction={() => setQuery("")}
        />
      ) : (
        <div className="plan-grid">
          {filtered.map((plan) => {
            const first = plan.options[0];
            return (
              <button
                className="plan-card"
                key={plan.id}
                onClick={() => onOpenPlan(plan)}
              >
                <div className="plan-cover">
                  <img
                    src="/images/shanghai.jpg"
                    alt={`${tripDestination(first, resources)}城市风景`}
                  />
                  <span className="cover-badge">
                    <Check size={12} />
                    已保存
                  </span>
                  <div>
                    <small>YOUR NEXT JOURNEY</small>
                    <h2>{tripDestination(first, resources)}</h2>
                  </div>
                </div>
                <div className="plan-card-body">
                  <h3>{first.label}</h3>
                  <div className="meta-line">
                    <CalendarDays size={14} />
                    {rangeLabel(first.start, first.end)}
                  </div>
                  <div className="plan-card-footer">
                    <span>{plan.options.length} 套可比较方案</span>
                    <span>
                      查看行程
                      <ArrowUpRight size={15} />
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
export function PlanDetail({
  plan,
  resources,
  onClose,
  submit,
  onRepair,
}: {
  plan: Plan;
  resources: Resource[];
  onClose: () => void;
  submit: Submit;
  onRepair: () => void;
}) {
  return (
    <Modal
      wide
      title={`${tripDestination(plan.options[0], resources)}旅行计划`}
      description="方案已保存；选择后可查看冻结报价，再决定是否预订。"
      onClose={onClose}
    >
      <div className="plan-detail-toolbar">
        <span className="meta-line">
          <CalendarDays size={15} />
          {rangeLabel(plan.options[0].start, plan.options[0].end)}
        </span>
        <button className="button button-secondary" onClick={onRepair}>
          <RefreshCw size={15} />
          调整行程
        </button>
      </div>
      <TripOptions
        options={plan.options}
        resources={resources}
        onChoose={async (option, index) => {
          if (
            await submit(
              bookingMessage(option, index, resources),
              requestForOption(option),
              true,
            )
          )
            onClose();
        }}
      />
    </Modal>
  );
}
export function OrdersPage({
  orders,
  resources,
  submit,
  onChange,
}: {
  orders: Order[];
  resources: Resource[];
  submit: Submit;
  onChange: (o: Order) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Order | null>(null);
  const rows = orders.filter(
    (o) =>
      (filter === "all" || o.status === filter) &&
      (resources.find((r) => r.id === o.resource)?.name || "").includes(query),
  );
  function card(order: Order, detail = false) {
    const resource = resources.find((r) => r.id === order.resource);
    const dates = orderDates(order.slots, resource);
    return (
      <>
        <div className="order-main">
          <span
            className={`resource-icon ${resource?.kind === "hotel" ? "hotel-icon" : ""}`}
          >
            {resource?.kind === "hotel" ? (
              <Hotel size={24} />
            ) : (
              <Plane size={24} />
            )}
          </span>
          <div className="order-summary">
            <div className="inline-heading">
              <h3>{resource?.name || "旅行预订"}</h3>
              <Badge status={order.status}>
                {order.status === "CANCELLED" ? "已取消" : undefined}
              </Badge>
            </div>
            <p>
              {resource?.kind === "flight"
                ? `${resource.details.departure} → ${resource.details.destination}`
                : `${resource?.details.destination || "目的地"} · 住宿安排`}
            </p>
            <div className="meta-line">
              <CalendarDays size={14} />
              {resource?.kind === "hotel"
                ? rangeLabel(dates.start, dates.end)
                : dateLabel(dates.start)}
              <span>·</span>
              {order.quantity || 1}
              {resource?.kind === "hotel" ? " 间" : " 位旅客"}
            </div>
          </div>
          <div className="order-price">
            <small>订单金额</small>
            <strong>{money(order.amount)}</strong>
          </div>
        </div>
        {detail && (
          <div className="detail-grid">
            <div>
              <span>订单状态</span>
              <strong>
                {order.status === "CONFIRMED" ? "预订已确认" : "预订已取消"}
              </strong>
            </div>
            <div>
              <span>预订内容</span>
              <strong>
                {resource?.kind === "hotel" ? "酒店住宿" : "航班座位"}
              </strong>
            </div>
          </div>
        )}
        <div className="order-footer">
          <span>
            <ShieldCheck size={14} />
            变更与取消均需您再次确认
          </span>
          <div>
            <button
              className="text-button"
              onClick={() => {
                setSelected(null);
                submit(
                  `请查询${resource?.name || "这项预订"}订单适用的取消与变更政策。`,
                  { intent: "policy", order_id: order.id },
                  true,
                );
              }}
            >
              查询适用政策
            </button>
            {!detail && (
              <button
                className="text-button"
                onClick={() => setSelected(order)}
              >
                订单详情
                <ChevronRight size={14} />
              </button>
            )}
            {order.status === "CONFIRMED" && (
              <>
                <button
                  className="button button-secondary button-small"
                  onClick={() => {
                    setSelected(null);
                    onChange(order);
                  }}
                >
                  变更预订
                </button>
                <button
                  className="text-button danger-text"
                  onClick={() => {
                    setSelected(null);
                    submit(
                      `我想取消${resource?.name || "这项预订"}，请先核对费用和条件。`,
                      {
                        intent: "cancel",
                        question: "请核对这笔订单的取消费与适用条件。",
                        order_id: order.id,
                      },
                      true,
                    );
                  }}
                >
                  申请取消
                </button>
              </>
            )}
          </div>
        </div>
      </>
    );
  }
  return (
    <div className="page">
      <PageHeader
        eyebrow="ALL YOUR RESERVATIONS"
        title="预订订单"
        text="交通与住宿，一目了然。变更之前，先核对每一项条件。"
      />
      <div className="page-toolbar">
        <div className="filter-tabs">
          {[
            ["all", "全部预订"],
            ["CONFIRMED", "有效预订"],
            ["CANCELLED", "已取消"],
          ].map(([id, label]) => (
            <button
              key={id}
              onClick={() => setFilter(id)}
              className={filter === id ? "active" : ""}
            >
              {label}
              <span>
                {orders.filter((o) => id === "all" || o.status === id).length}
              </span>
            </button>
          ))}
        </div>
        <label className="search-field">
          <Search size={16} />
          <input
            placeholder="搜索预订名称"
            aria-label="搜索订单"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      {!orders.length ? (
        <div className="panel">
          <Empty
            icon={<Ticket size={30} />}
            title="还没有旅行预订"
            text="确认行程中的预订报价后，机票与酒店订单会出现在这里。"
          />
        </div>
      ) : !rows.length ? (
        <Empty
          icon={<Search size={27} />}
          title="没有匹配的预订"
          text="试着调整筛选条件或关键词。"
        />
      ) : (
        <div className="order-list">
          {rows.map((order) => (
            <article className="order-card" key={order.id}>
              {card(order)}
            </article>
          ))}
        </div>
      )}
      {selected && (
        <Modal title="预订详情" onClose={() => setSelected(null)} wide>
          <div className="order-detail">{card(selected, true)}</div>
        </Modal>
      )}
    </div>
  );
}
export function SupportPage({
  user,
  cases,
  onCreate,
  onAdmin,
  busy,
}: {
  user: User;
  cases: Case[];
  onCreate: () => void;
  onAdmin: (path: string, body: unknown) => Promise<boolean>;
  busy: boolean;
}) {
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [reply, setReply] = useState<Case | null>(null);
  const [text, setText] = useState("");
  const [close, setClose] = useState(false);
  const [replyBusy, setReplyBusy] = useState(false);
  const rows = cases.filter(
    (c) =>
      filter === "all" ||
      (filter === "active" && c.status !== "CLOSED") ||
      (filter === "CLOSED" && c.status === "CLOSED"),
  );
  const selected = rows.find((c) => c.id === selectedId) || rows[0];
  return (
    <div className="page">
      <PageHeader
        eyebrow="WE’RE HERE TO HELP"
        title={user.role === "admin" ? "客服工作台" : "服务中心"}
        text={
          user.role === "admin"
            ? "接续每一次对话，认真处理每一个旅行问题。"
            : "需要多一点帮助时，我们始终在这里。"
        }
      >
        <button className="button button-primary" onClick={onCreate}>
          <Plus size={16} />
          发起服务申请
        </button>
      </PageHeader>
      <div className="service-intro">
        <span>
          <Headphones size={23} />
        </span>
        <div>
          <strong>让问题有回应，让出发更安心</strong>
          <p>订单与费用、改签取消、行程调整，都可以在这里继续沟通。</p>
        </div>
        <ShieldCheck size={27} />
      </div>
      <div className="page-toolbar">
        <div className="filter-tabs">
          {[
            ["all", "全部申请"],
            ["active", "处理中"],
            ["CLOSED", "已结束"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={filter === id ? "active" : ""}
              onClick={() => setFilter(id)}
            >
              {label}
              <span>
                {
                  cases.filter(
                    (c) =>
                      id === "all" ||
                      (id === "active" && c.status !== "CLOSED") ||
                      (id === "CLOSED" && c.status === "CLOSED"),
                  ).length
                }
              </span>
            </button>
          ))}
        </div>
      </div>
      {!rows.length ? (
        <div className="panel">
          <Empty
            icon={<Headphones size={30} />}
            title={
              cases.length
                ? "没有这一状态的服务申请"
                : "有任何问题，随时告诉我们"
            }
            text="提交说明并确认后，您可以在这里跟进处理状态和客服答复。"
            action="联系人工客服"
            onAction={onCreate}
          />
        </div>
      ) : (
        <div className="service-workspace">
          <div className="case-list">
            {rows.map((item) => (
              <button
                key={item.id}
                className={`case-item ${selected?.id === item.id ? "selected" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div>
                  <span className="case-symbol">
                    <MessageCircle size={17} />
                  </span>
                  <Badge status={item.status} />
                </div>
                <strong>
                  {item.context.request?.question || "旅行服务咨询"}
                </strong>
                <small>
                  {user.role === "admin" ? `${item.customer} · ` : ""}
                  {item.replies.length
                    ? `${item.replies.length} 条沟通记录`
                    : "等待接续处理"}
                </small>
              </button>
            ))}
          </div>
          {selected && (
            <section className="case-detail">
              <div className="case-detail-header">
                <div>
                  <h3>旅行服务申请</h3>
                  <p>
                    {user.role === "admin"
                      ? selected.customer
                      : "我们会在这里持续跟进您的问题"}
                  </p>
                </div>
                <Badge status={selected.status} />
              </div>
              <div className="case-messages">
                <div className="case-message question-message">
                  <span className="message-caption">
                    {user.role === "admin" ? selected.customer : "我的说明"}
                  </span>
                  <Markdown
                    text={selected.context.request?.question || "旅行服务咨询"}
                  />
                </div>
                {selected.replies.map((item, index) => (
                  <div className="case-message reply-message" key={index}>
                    <span className="message-caption">
                      <Headphones size={13} />
                      {item.role === "user"
                        ? item.by === user.id
                          ? "我的补充"
                          : selected.customer
                        : user.role === "admin" && item.by === user.id
                          ? "我的回复"
                          : "人工客服"}
                    </span>
                    <Markdown text={item.text} />
                  </div>
                ))}
                {!selected.replies.length && (
                  <div className="case-waiting">
                    <ClockNotice />
                    <p>
                      {selected.assigned
                        ? "客服已接续您的申请，回复会展示在这里。"
                        : "申请已收到，等待客服接续处理。"}
                    </p>
                  </div>
                )}
              </div>
              {user.role !== "admin" && selected.status !== "CLOSED" && (
                <div className="case-admin-actions">
                  <button
                    className="button button-primary"
                    onClick={() => {
                      setReply(selected);
                      setText("");
                      setClose(false);
                    }}
                  >
                    补充说明
                  </button>
                </div>
              )}
              {user.role === "admin" && selected.status !== "CLOSED" && (
                <div className="case-admin-actions">
                  {!selected.assigned ? (
                    <button
                      className="button button-primary"
                      disabled={busy}
                      onClick={() =>
                        onAdmin(`/api/cases/${selected.id}/claim`, {})
                      }
                    >
                      核对并领取申请
                      <ArrowRight size={16} />
                    </button>
                  ) : selected.assigned === user.id ? (
                    <button
                      className="button button-primary"
                      onClick={() => {
                        setReply(selected);
                        setText("");
                        setClose(false);
                      }}
                    >
                      回复旅客
                      <MessageCircle size={16} />
                    </button>
                  ) : (
                    <p className="muted">这份申请已由其他客服领取。</p>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      )}
      {reply && (
        <Modal
          title={user.role === "admin" ? "回复服务申请" : "补充服务申请"}
          description={
            user.role === "admin"
              ? "回复和关闭操作会先生成待确认内容，确认后才会发送。"
              : "补充内容会先交给您核对，确认后才会发送到原工单。"
          }
          onClose={() => setReply(null)}
        >
          <form
            className="product-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setReplyBusy(true);
              const ok = await onAdmin(
                `/api/cases/${reply.id}/${user.role === "admin" ? "reply" : "messages"}`,
                {
                  text: text.trim(),
                  close,
                },
              );
              setReplyBusy(false);
              if (ok) setReply(null);
            }}
          >
            <div className="form-context">
              <MessageCircle size={18} />
              <p>{reply.context.request?.question}</p>
            </div>
            <label>
              回复内容
              <textarea
                rows={6}
                maxLength={2000}
                required
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="说明已核实的信息与下一步建议…"
              />
            </label>
            {user.role === "admin" && (
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={close}
                  onChange={(e) => setClose(e.target.checked)}
                />
                回复后结束这份服务申请
              </label>
            )}
            <div className="modal-footer">
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setReply(null)}
              >
                取消
              </button>
              <button
                className="button button-primary"
                disabled={replyBusy || !text.trim()}
              >
                {replyBusy ? <Spinner label="提交中" /> : "继续核对回复"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
function ClockNotice() {
  return (
    <span className="waiting-dots">
      <i />
      <i />
      <i />
    </span>
  );
}
export function KnowledgePage({
  revisions,
  onImport,
  onAdmin,
  busy,
}: {
  revisions: Revision[];
  onImport: () => void;
  onAdmin: (p: string, b: unknown) => Promise<boolean>;
  busy: boolean;
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const rows = revisions.filter(
    (r) =>
      (filter === "all" || r.status === filter) &&
      `${r.document} ${r.supplier} ${r.product} ${r.source}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <div className="page">
      <PageHeader
        eyebrow="TRUSTED INFORMATION"
        title="知识管理"
        text="让每一次解答都有依据，让每一版政策可追溯。"
      >
        <button className="button button-primary" onClick={onImport}>
          <UploadCloud size={16} />
          导入文档
        </button>
      </PageHeader>
      <div className="knowledge-stats">
        {[
          ["全部版本", revisions.length, FileText],
          [
            "已发布",
            revisions.filter((r) => r.status === "PUBLISHED").length,
            BookOpen,
          ],
          [
            "待发布",
            revisions.filter((r) => r.status === "VERIFIED").length,
            ShieldCheck,
          ],
        ].map(([label, count, Icon]) => {
          const I = Icon as typeof FileText;
          return (
            <div key={String(label)}>
              <I size={21} />
              <span>{String(label)}</span>
              <strong>{String(count)}</strong>
            </div>
          );
        })}
      </div>
      <div className="page-toolbar">
        <div className="filter-tabs">
          {[
            ["all", "全部文档"],
            ["PUBLISHED", "已发布"],
            ["VERIFIED", "待发布"],
            ["REVOKED", "已撤回"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={filter === id ? "active" : ""}
              onClick={() => setFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="search-field">
          <Search size={16} />
          <input
            placeholder="搜索文档、供应商或产品"
            aria-label="搜索知识文档"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      {!rows.length ? (
        <div className="panel">
          <Empty
            icon={<BookOpen size={30} />}
            title={
              revisions.length ? "没有找到对应文档" : "为旅行助手添加第一份依据"
            }
            text="导入政策或指南，核对适用范围并发布后，助手才能使用。"
            action={revisions.length ? "清除筛选" : "导入文档"}
            onAction={
              revisions.length
                ? () => {
                    setQuery("");
                    setFilter("all");
                  }
                : onImport
            }
          />
        </div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>文档</th>
                <th>适用范围</th>
                <th>有效日期</th>
                <th>状态</th>
                <th className="align-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="document-cell">
                      <span>
                        <FileText size={20} />
                      </span>
                      <div>
                        <strong>{row.document}</strong>
                        <small>{row.source}</small>
                        {row.error && (
                          <small className="danger-text">
                            导入异常：{row.error}
                          </small>
                        )}
                      </div>
                    </div>
                  </td>
                  <td>
                    <strong>{row.supplier}</strong>
                    <small>{row.product}</small>
                  </td>
                  <td>
                    <span>{row.valid_from}</span>
                    <small>至 {row.valid_to}</small>
                  </td>
                  <td>
                    <Badge status={row.status} />
                  </td>
                  <td>
                    <div className="table-actions">
                      {row.status === "VERIFIED" && (
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            onAdmin(`/api/knowledge/${row.id}/publish`, {})
                          }
                        >
                          发布
                          <ArrowUpRight size={13} />
                        </button>
                      )}
                      {row.status === "PUBLISHED" && (
                        <button
                          className="text-button danger-text"
                          disabled={busy}
                          onClick={() =>
                            onAdmin(`/api/knowledge/${row.id}/revoke`, {})
                          }
                        >
                          撤回
                        </button>
                      )}
                      {row.status === "REVOKED" && (
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            onAdmin(`/api/knowledge/${row.id}/rollback`, {})
                          }
                        >
                          核对恢复
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="notice knowledge-notice">
        <ShieldCheck size={18} />
        <span>
          导入、发布、撤回和恢复都需要再次确认。新版本请核对生效日期，已发布的历史内容会保留。
        </span>
      </div>
    </div>
  );
}
