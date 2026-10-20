import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  Check,
  ChevronDown,
  Compass,
  Eye,
  EyeOff,
  Headphones,
  Home as HomeIcon,
  LogOut,
  Luggage,
  Menu,
  MessageCircle,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Ticket,
  X,
} from "lucide-react";
import { api, ApiError, followRun } from "./api";
import type {
  ChatEntry,
  Conversation,
  Case,
  Order,
  Page,
  Plan,
  Resource,
  Revision,
  Run,
  Submit,
  User,
} from "./types";
import { active, friendlyError, intentLabels } from "./lib";
import {
  AssistantAvatar,
  Brand,
  Empty,
  Modal,
  Skeleton,
  Spinner,
} from "./components/ui";
import { RunCard } from "./components/Results";
import {
  Home,
  KnowledgePage,
  OrdersPage,
  PlanDetail,
  PlansPage,
  SupportPage,
} from "./components/Pages";
import { ConversationManager } from "./components/ConversationManager";
import { KnowledgeForm, SupportForm, TripForm } from "./components/Forms";
const labels: Record<Page, string> = {
  home: "旅行工作台",
  assistant: "旅行助手",
  plans: "我的行程",
  orders: "预订订单",
  support: "服务中心",
  knowledge: "知识管理",
};
function route() {
  const [page, id] = location.hash.slice(1).split("/");
  return {
    page: (Object.keys(labels).includes(page) ? page : "home") as Page,
    cid: page === "assistant" ? id || "" : "",
  };
}
export default function App() {
  const [token, setToken] = useState(
    sessionStorage.getItem("travelmate_token") || "",
  );
  const [user, setUser] = useState<User | null>(null);
  const [restoring, setRestoring] = useState(!!token);
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const [locationState, setLocationState] = useState(route);
  const currentCid = useRef(locationState.cid);
  currentCid.current = locationState.cid;
  const lastConversation = useRef(locationState.cid);
  if (locationState.cid) lastConversation.current = locationState.cid;
  const [mobile, setMobile] = useState(false);
  const [account, setAccount] = useState(false);
  const [inbox, setInbox] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [resources, setResources] = useState<Resource[]>([]);
  const resourcesLoadedFor = useRef("");
  const [plans, setPlans] = useState<Plan[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [dataError, setDataError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [optimistic, setOptimistic] = useState("");
  const [stage, setStage] = useState("");
  const [draft, setDraft] = useState("");
  const [trip, setTrip] = useState<{
    mode: "plan" | "search" | "repair" | "change";
    plan?: Plan;
    order?: Order;
  } | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [support, setSupport] = useState(false);
  const [importing, setImporting] = useState(false);
  const chatEnd = useRef<HTMLDivElement>(null);
  function navigate(page: Page, cid = "") {
    const value = { page, cid: page === "assistant" ? cid : "" };
    currentCid.current = value.cid;
    setLocationState(value);
    location.hash = page + (value.cid ? "/" + value.cid : "");
    setMobile(false);
    setDraft("");
  }
  function logout() {
    sessionStorage.removeItem("travelmate_token");
    tokenRef.current = "";
    setToken("");
    setUser(null);
    setEntries([]);
    setRuns([]);
    setConversations([]);
    setPlans([]);
    setOrders([]);
    setCases([]);
    setRevisions([]);
    setResources([]);
    resourcesLoadedFor.current = "";
    setAccount(false);
    setInbox(false);
    setHistoryOpen(false);
    lastConversation.current = "";
    setTrip(null);
    setSelectedPlan(null);
    setSupport(false);
    setImporting(false);
    setDataError("");
    navigate("home");
  }
  function error(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      logout();
      setToast("登录已过期，请重新登录。");
    } else setToast(friendlyError(error));
  }
  useEffect(() => {
    const fn = () => {
      setLocationState(route());
      setMobile(false);
    };
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 6500);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (!token) return;
    const abort = new AbortController();
    setRestoring(true);
    api<User>("/api/me", token, undefined, abort.signal)
      .then(setUser)
      .catch((e) => {
        if (!abort.signal.aborted) error(e);
      })
      .finally(() => {
        if (!abort.signal.aborted) setRestoring(false);
      });
    return () => abort.abort();
  }, [token]);
  async function refresh() {
    if (!tokenRef.current || !user) return;
    const key = tokenRef.current;
    const includeResources = resourcesLoadedFor.current !== key;
    const paths = [
      ...(includeResources ? ["/api/resources"] : []),
      "/api/plans",
      "/api/orders",
      "/api/cases",
      "/api/conversations",
      "/api/runs",
      ...(user.role === "admin" ? ["/api/knowledge/revisions"] : []),
    ];
    const setters = [
      ...(includeResources ? [setResources] : []),
      setPlans,
      setOrders,
      setCases,
      setConversations,
      setRuns,
      setRevisions,
    ];
    const results = await Promise.allSettled(paths.map((p) => api(p, key)));
    if (key !== tokenRef.current) return;
    let failed = false;
    results.forEach((result, i) => {
      if (result.status === "fulfilled") {
        setters[i](result.value);
        if (includeResources && i === 0) resourcesLoadedFor.current = key;
      } else {
        failed = true;
        if (result.reason instanceof ApiError && result.reason.status === 401)
          error(result.reason);
      }
    });
    setDataError(
      failed
        ? "部分内容暂时无法加载，请重试。若刚更新项目，请重新启动后端服务。"
        : "",
    );
  }
  useEffect(() => {
    if (!user) return;
    setLoading(true);
    refresh().finally(() => setLoading(false));
  }, [user?.id]);
  async function loadChat(cid: string, key = tokenRef.current) {
    const value = await api<{ messages: ChatEntry[] }>(
      `/api/conversations/${cid}`,
      key,
    );
    if (key === tokenRef.current && cid === currentCid.current)
      setEntries(value.messages);
  }
  useEffect(() => {
    setEntries([]);
    if (!submitting.current) setOptimistic("");
    if (!locationState.cid || !token) return;
    const cid = locationState.cid;
    let cancelled = false;
    setChatLoading(true);
    loadChat(cid)
      .catch((e) => {
        if (!cancelled) error(e);
      })
      .finally(() => {
        if (!cancelled) setChatLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [locationState.cid, token]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const key = token;
    const poll = async () => {
      if (document.hidden) return;
      try {
        const values = await api<Run[]>("/api/runs", key);
        if (cancelled) return;
        setRuns((previous) => {
          if (
            values.some(
              (r) => previous.find((p) => p.id === r.id)?.status !== r.status,
            )
          )
            void refreshRef.current();
          return values;
        });
        setEntries((previous) =>
          previous.map((entry) => ({
            ...entry,
            run: values.find((r) => r.id === entry.run?.id) || entry.run,
          })),
        );
        // 客服回复和知识状态也会由其他账号更新，不能只依赖本人的 Run 状态变化。
        if (locationState.page === "support") {
          const items = await api<Case[]>("/api/cases", key);
          if (!cancelled) setCases(items);
        } else if (
          locationState.page === "knowledge" &&
          user.role === "admin"
        ) {
          const items = await api<Revision[]>("/api/knowledge/revisions", key);
          if (!cancelled) setRevisions(items);
        }
      } catch (e) {
        if (!cancelled && e instanceof ApiError && e.status === 401) error(e);
      }
    };
    const timer = setInterval(poll, 3500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [user?.id, token, locationState.page]);
  const latest = entries.at(-1)?.run;
  const processingRun = entries
    .map((e) => e.run)
    .find((r) => r && ["QUEUED", "RUNNING"].includes(r.status));
  const processing = !!processingRun;
  useEffect(() => {
    if (!processingRun) return;
    const abort = new AbortController();
    setStage("正在安排您的需求");
    followRun(processingRun.id, token, abort.signal, setStage, (value) => {
      if (abort.signal.aborted) return;
      setEntries((previous) =>
        previous.map((e) =>
          e.run?.id === value.id ? { ...e, run: value } : e,
        ),
      );
      setRuns((previous) => [
        value,
        ...previous.filter((r) => r.id !== value.id),
      ]);
      void refreshRef.current();
    }).catch(() => {});
    return () => abort.abort();
  }, [processingRun?.id, processing, token]);
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries.length, optimistic, latest?.status]);
  const submit: Submit = async (text, request, newConversation = false) => {
    if (submitting.current) return false;
    if (!newConversation && processing) {
      setToast(
        latest?.status === "WAITING"
          ? "请先处理当前对话中的待确认内容。"
          : "当前需求仍在处理中，请等待完成或先停止处理。",
      );
      return false;
    }
    submitting.current = true;
    setBusy(true);
    setOptimistic(text);
    const key = tokenRef.current;
    try {
      let cid = newConversation ? "" : currentCid.current;
      if (!cid)
        cid = (await api<{ id: string }>("/api/conversations", key, {})).id;
      if (key !== tokenRef.current) return false;
      if (cid !== currentCid.current || locationState.page !== "assistant")
        navigate("assistant", cid);
      setOptimistic(text);
      const result = await api<{ run_id: string }>(
        `/api/conversations/${cid}/messages`,
        key,
        {
          text,
          ...(request ? { request: { ...request, question: text } } : {}),
        },
      );
      const value = await api<Run>(`/api/runs/${result.run_id}`, key);
      if (key !== tokenRef.current) return false;
      setRuns((previous) => [
        value,
        ...previous.filter((r) => r.id !== value.id),
      ]);
      await loadChat(cid, key);
      void refresh();
      return true;
    } catch (e) {
      if (!request && key === tokenRef.current) setDraft(text);
      error(e);
      return false;
    } finally {
      setOptimistic("");
      setBusy(false);
      submitting.current = false;
    }
  };
  async function decision(run: Run, value: "approve" | "reject") {
    if (busy) return;
    setBusy(true);
    try {
      if (
        value === "reject" &&
        run.result.approval!.proposal.expires < Date.now() / 1000
      ) {
        await api(`/api/runs/${run.id}/cancel`, token, {});
      } else {
        await api(`/api/runs/${run.id}/approval`, token, {
          decision: value,
          version: run.result.approval!.proposal.version,
        });
      }
      const updated = await api<Run>(`/api/runs/${run.id}`, token);
      setEntries((prev) =>
        prev.map((e) => (e.run?.id === run.id ? { ...e, run: updated } : e)),
      );
      setInbox(false);
      navigate("assistant", run.conversation_id);
      await loadChat(run.conversation_id);
      await refresh();
    } catch (e) {
      error(e);
    } finally {
      setBusy(false);
    }
  }
  async function stop(run: Run) {
    setBusy(true);
    try {
      await api(`/api/runs/${run.id}/cancel`, token, {});
      await loadChat(run.conversation_id);
      await refresh();
    } catch (e) {
      error(e);
    } finally {
      setBusy(false);
    }
  }
  async function renew(run: Run) {
    if (busy || submitting.current) return;
    setBusy(true);
    try {
      await api(`/api/runs/${run.id}/retry`, token, {});
      navigate("assistant", run.conversation_id);
      await loadChat(run.conversation_id);
      await refresh();
    } catch (e) {
      error(e);
    } finally {
      setBusy(false);
    }
  }
  async function admin(path: string, body: unknown) {
    if (busy) return false;
    setBusy(true);
    try {
      const value = await api<{ run_id: string }>(path, token, body);
      const run = await api<Run>(`/api/runs/${value.run_id}`, token);
      navigate("assistant", run.conversation_id);
      await loadChat(run.conversation_id);
      await refresh();
      return true;
    } catch (e) {
      error(e);
      return false;
    } finally {
      setBusy(false);
    }
  }
  const waiting = runs.filter((r) => r.status === "WAITING");
  const navItems = [
    ["home", HomeIcon],
    ["assistant", Sparkles],
    ["plans", Luggage],
    ["orders", Ticket],
    ["support", Headphones],
    ...(user?.role === "admin" ? [["knowledge", BookOpen]] : []),
  ] as [Page, typeof HomeIcon][];
  if (restoring)
    return (
      <div className="app-loading">
        <Brand />
        <Spinner label="正在打开旅行工作台" />
      </div>
    );
  if (!user)
    return (
      <>
        <Login
          onLogin={(value) => {
            sessionStorage.setItem("travelmate_token", value);
            setToken(value);
          }}
        />
        {toast && (
          <div className="toast" role="alert">
            {toast}
            <button onClick={() => setToast("")} aria-label="关闭提示">
              <X size={16} />
            </button>
          </div>
        )}
      </>
    );
  const content =
    locationState.page === "home" ? (
      <Home
        user={user}
        plans={plans}
        orders={orders}
        runs={runs}
        resources={resources}
        navigate={(p) => {
          if (p === "assistant" && waiting.length) setInbox(true);
          else navigate(p);
        }}
        onPlan={() => setTrip({ mode: "plan" })}
        onSearch={() => setTrip({ mode: "search" })}
        onSupport={() => setSupport(true)}
        onOpenPlan={setSelectedPlan}
        submit={submit}
      />
    ) : locationState.page === "plans" ? (
      <PlansPage
        plans={plans}
        resources={resources}
        onPlan={() => setTrip({ mode: "plan" })}
        onOpenPlan={setSelectedPlan}
      />
    ) : locationState.page === "orders" ? (
      <OrdersPage
        orders={orders}
        resources={resources}
        submit={submit}
        onChange={(order) => setTrip({ mode: "change", order })}
      />
    ) : locationState.page === "support" ? (
      <SupportPage
        user={user}
        cases={cases}
        onCreate={() => setSupport(true)}
        onAdmin={admin}
        busy={busy}
      />
    ) : locationState.page === "knowledge" && user.role === "admin" ? (
      <KnowledgePage
        revisions={revisions}
        onImport={() => setImporting(true)}
        onAdmin={admin}
        busy={busy}
      />
    ) : null;
  return (
    <div className="app-shell">
      {mobile && (
        <div className="sidebar-scrim" onClick={() => setMobile(false)} />
      )}
      <aside className={`sidebar ${mobile ? "sidebar-open" : ""}`}>
        <a
          className="brand-link"
          href="#home"
          onClick={() => navigate("home")}
          aria-label="TravelMate 首页"
        >
          <Brand />
        </a>
        <button
          className="new-chat button"
          onClick={() => navigate("assistant")}
        >
          <Plus size={17} />
          开启新的对话<span>↗</span>
        </button>
        <div className="nav-caption">旅行空间</div>
        <nav>
          {navItems.map(([page, Icon]) => (
            <button
              key={page}
              className={`nav-item ${locationState.page === page ? "active" : ""}`}
              onClick={() => {
                if (locationState.page !== page)
                  navigate(
                    page,
                    page === "assistant" ? lastConversation.current : "",
                  );
                setMobile(false);
              }}
            >
              <Icon size={19} />
              <span>{labels[page]}</span>
              {page === "assistant" && <span className="nav-ai">AI</span>}
              {page === "plans" && plans.length > 0 && (
                <span className="nav-count">{plans.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-recent">
          <div className="nav-caption">最近对话</div>
          <button
            onClick={() => {
              setHistoryOpen(true);
              setMobile(false);
            }}
          >
            <Search size={14} />
            <span>会话管理</span>
          </button>
          {conversations.length ? (
            conversations.slice(0, 6).map((c) => (
              <button
                key={c.id}
                title={c.title}
                className={locationState.cid === c.id ? "current" : ""}
                onClick={() => navigate("assistant", c.id)}
              >
                <MessageCircle size={14} />
                <span>{c.title}</span>
              </button>
            ))
          ) : (
            <p>
              聊聊下一段旅行，
              <br />
              对话会自动保存在这里。
            </p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Compass size={20} />
            <div>
              <strong>每一程，都有好安排</strong>
              <span>灵感 · 规划 · 预订 · 服务</span>
            </div>
          </div>
          <div className="account-wrap">
            {account && (
              <div className="account-menu">
                <span>
                  {user.role === "admin" ? "管理员工作空间" : "我的旅行空间"}
                </span>
                <button onClick={logout}>
                  <LogOut size={16} />
                  退出登录
                </button>
              </div>
            )}
            <button
              className="account-button"
              onClick={() => setAccount(!account)}
              aria-expanded={account}
            >
              <span className="user-avatar">
                {user.name.slice(0, 1).toUpperCase()}
              </span>
              <div>
                <strong>{user.name}</strong>
                <small>
                  {user.role === "admin" ? "客服与知识管理" : "旅行者"}
                </small>
              </div>
              <ChevronDown size={15} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button mobile-menu"
              onClick={() => setMobile(true)}
              aria-label="打开导航"
            >
              <Menu size={21} />
            </button>
            <span>我的空间</span>
            <span className="breadcrumb-slash">/</span>
            <strong>{labels[locationState.page]}</strong>
          </div>
          <div className="topbar-actions">
            <span className="topbar-note">
              <ShieldCheck size={14} />
              您的安排，由您确认
            </span>
            <button
              className="notification-button icon-button"
              onClick={() => setInbox(true)}
              aria-label={`待确认事项 ${waiting.length} 项`}
            >
              <Bell size={19} />
              {waiting.length > 0 && <span>{waiting.length}</span>}
            </button>
            <button
              className="topbar-avatar"
              aria-label="账户菜单"
              onClick={() => {
                if (window.matchMedia("(max-width:700px)").matches)
                  setMobile(true);
                setAccount(!account);
              }}
            >
              {user.name.slice(0, 1).toUpperCase()}
            </button>
          </div>
        </header>
        {dataError && (
          <div className="data-error" role="alert">
            {dataError}
            <button onClick={() => refresh()}>重新加载</button>
          </div>
        )}
        {locationState.page === "assistant" ? (
          <section className="chat-page">
            <div className="chat-heading">
              <div>
                <AssistantAvatar />
                <div>
                  <strong
                    title={
                      conversations.find((c) => c.id === locationState.cid)
                        ?.title
                    }
                  >
                    {conversations.find((c) => c.id === locationState.cid)
                      ?.title || "TravelMate 旅行助手"}
                  </strong>
                  <span>从旅行灵感，到妥帖安排</span>
                </div>
              </div>
            </div>
            <div className="chat-scroll">
              {chatLoading ? (
                <div className="chat-loading">
                  <Spinner label="正在恢复对话" />
                </div>
              ) : !entries.length && !optimistic ? (
                <div className="chat-welcome">
                  <div className="welcome-symbol">
                    <Sparkles size={32} />
                  </div>
                  <span className="eyebrow">GOOD PLANS START HERE</span>
                  <h1>下一程，想去哪里？</h1>
                  <p>
                    一个目的地、一点灵感，或一个需要解答的问题。
                    <br />
                    我们一起，把旅程安排好。
                  </p>
                  <div className="prompt-grid">
                    <button onClick={() => setTrip({ mode: "plan" })}>
                      <Luggage size={22} />
                      <strong>一起规划旅程</strong>
                      <span>按日期、人数和预算，比较旅行方案</span>
                      <ArrowUpRight size={16} />
                    </button>
                    <button onClick={() => setTrip({ mode: "search" })}>
                      <Search size={22} />
                      <strong>寻找机票与住宿</strong>
                      <span>查看真实可用资源与预订条件</span>
                      <ArrowUpRight size={16} />
                    </button>
                    <button
                      onClick={() => setDraft("酒店取消有哪些条件和费用？")}
                    >
                      <BookOpen size={22} />
                      <strong>读懂旅行政策</strong>
                      <span>查询条款，查看回答的原文依据</span>
                      <ArrowUpRight size={16} />
                    </button>
                    <button onClick={() => setSupport(true)}>
                      <Headphones size={22} />
                      <strong>需要更多帮助</strong>
                      <span>说明问题，让人工客服接续处理</span>
                      <ArrowUpRight size={16} />
                    </button>
                  </div>
                </div>
              ) : (
                <div className="chat-messages">
                  {entries.map((entry, index) => (
                    <div className="exchange" key={entry.run?.id || index}>
                      <div className="user-message">
                        <div>{entry.text}</div>
                        <span className="user-avatar">
                          {user.name.slice(0, 1).toUpperCase()}
                        </span>
                      </div>
                      <div className="assistant-message">
                        <AssistantAvatar />
                        <div className="assistant-body">
                          <span className="assistant-name">
                            TravelMate <small>旅行助手</small>
                          </span>
                          {entry.run ? (
                            <RunCard
                              run={entry.run}
                              resources={resources}
                              submit={submit}
                              onDecision={decision}
                              busy={busy}
                              stage={stage}
                              onStop={stop}
                              onRenew={renew}
                              onSupport={() => setSupport(true)}
                            />
                          ) : (
                            <p className="muted">
                              这条历史消息未关联处理记录，您可以重新发起咨询。
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                  {optimistic && (
                    <>
                      <div className="user-message">
                        <div>{optimistic}</div>
                        <span className="user-avatar">
                          {user.name.slice(0, 1).toUpperCase()}
                        </span>
                      </div>
                      <div className="assistant-message">
                        <AssistantAvatar />
                        <Spinner label="正在提交您的需求" />
                      </div>
                    </>
                  )}
                  <div ref={chatEnd} />
                </div>
              )}
            </div>
            <div className="composer-area">
              {(active(latest) || processing) && (
                <div className="composer-pending">
                  <span>
                    {latest?.status === "WAITING"
                      ? "可继续询问费用和政策；修改需求前请先拒绝或取消待确认内容。"
                      : "助手正在处理当前需求，您可以随时停止。"}
                  </span>
                </div>
              )}
              <form
                className="composer"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!draft.trim() || processing || busy) return;
                  const text = draft;
                  if (await submit(text.trim())) setDraft("");
                }}
              >
                <textarea
                  aria-label="向旅行助手发送消息"
                  rows={2}
                  maxLength={4000}
                  placeholder="说说您的旅行想法，或问一个旅行问题…"
                  value={draft}
                  disabled={busy || !!processing}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      e.currentTarget.form?.requestSubmit();
                    }
                  }}
                />
                <div className="composer-bottom">
                  <span>
                    <Sparkles size={14} />
                    旅行安排，一起想周全
                  </span>
                  <div>
                    <small>Shift + Enter 换行</small>
                    <button
                      type="submit"
                      className="send-button"
                      aria-label="发送消息"
                      disabled={!draft.trim() || busy || !!processing}
                    >
                      <Send size={18} />
                    </button>
                  </div>
                </div>
              </form>
              <p className="composer-disclaimer">
                回答请结合原文核实。预订、变更与保存，均需您再次确认。
              </p>
            </div>
          </section>
        ) : (
          <main>
            {loading ? (
              <div className="page">
                <Skeleton />
              </div>
            ) : (
              content
            )}
          </main>
        )}
      </div>
      {trip && (
        <TripForm
          {...trip}
          resources={resources}
          submit={(text, request) =>
            submit(text, request, locationState.page !== "assistant")
          }
          onClose={() => setTrip(null)}
        />
      )}{" "}
      {historyOpen && (
        <ConversationManager
          conversations={conversations}
          currentId={locationState.cid}
          onClose={() => setHistoryOpen(false)}
          onOpen={(id) => {
            setHistoryOpen(false);
            navigate("assistant", id);
          }}
          onRename={async (id, title) => {
            await api(
              `/api/conversations/${id}`,
              token,
              { title },
              undefined,
              "PATCH",
            );
            setConversations((items) =>
              items.map((c) => (c.id === id ? { ...c, title } : c)),
            );
            setToast("会话名称已更新");
          }}
          onDelete={async (id) => {
            await api(
              `/api/conversations/${id}`,
              token,
              undefined,
              undefined,
              "DELETE",
            );
            setConversations((items) => items.filter((c) => c.id !== id));
            setRuns((items) => items.filter((r) => r.conversation_id !== id));
            if (lastConversation.current === id) lastConversation.current = "";
            if (currentCid.current === id) {
              setEntries([]);
              navigate("assistant");
            }
            setToast("会话已删除，业务记录已保留");
          }}
        />
      )}
      {selectedPlan && (
        <PlanDetail
          plan={selectedPlan}
          resources={resources}
          onClose={() => setSelectedPlan(null)}
          submit={submit}
          onRepair={() => {
            setTrip({ mode: "repair", plan: selectedPlan });
            setSelectedPlan(null);
          }}
        />
      )}
      {support && (
        <SupportForm
          orders={orders}
          resources={resources}
          submit={(text, request) =>
            submit(text, request, locationState.page !== "assistant")
          }
          onClose={() => setSupport(false)}
        />
      )}{" "}
      {importing && (
        <KnowledgeForm
          resources={resources}
          onSubmit={admin}
          onClose={() => setImporting(false)}
        />
      )}{" "}
      {inbox && (
        <Modal
          title="等待我的确认"
          description="核对安排的内容、费用与条件，再决定是否继续。"
          onClose={() => setInbox(false)}
        >
          {waiting.length ? (
            <div className="inbox-list">
              {waiting.map((run) => (
                <button
                  key={run.id}
                  onClick={() => {
                    setInbox(false);
                    navigate("assistant", run.conversation_id);
                  }}
                >
                  <span className="inbox-icon">
                    <ShieldCheck size={21} />
                  </span>
                  <div>
                    <strong>
                      {intentLabels[run.payload.intent] || "旅行安排"}
                    </strong>
                    <p>{run.payload.question || "查看待确认内容"}</p>
                  </div>
                  <ArrowRight size={17} />
                </button>
              ))}
            </div>
          ) : (
            <Empty
              icon={<Check size={28} />}
              title="所有安排，都已妥当"
              text="目前没有等待确认的事项，新安排准备好后会出现在这里。"
            />
          )}
        </Modal>
      )}
      {toast && (
        <div className="toast" role="alert">
          {toast}
          <button onClick={() => setToast("")} aria-label="关闭提示">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const value = await api<{ token: string }>("/api/login", "", {
        name: name.trim(),
        password,
      });
      onLogin(value.token);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "用户名或密码不正确，请重新输入。"
          : friendlyError(e),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <section className="login-visual">
        <Brand light />
        <div className="login-quote">
          <span className="hero-kicker">
            YOUR JOURNEY, BEAUTIFULLY ARRANGED
          </span>
          <h1>
            把期待交给远方，
            <br />
            把安排交给我们。
          </h1>
          <p>
            旅行灵感、行程规划、预订与陪伴。
            <br />
            每一段旅程，都值得从容以待。
          </p>
          <span className="login-location">
            <Compass size={16} />
            中国 · 上海
          </span>
        </div>
        <small>TRAVELMATE · EVERY JOURNEY MATTERS</small>
      </section>
      <section className="login-form-side">
        <div className="login-mobile-brand">
          <Brand />
        </div>
        <div className="login-form-wrap">
          <span className="eyebrow">WELCOME TO TRAVELMATE</span>
          <h2>欢迎回来</h2>
          <p>登录您的旅行空间，继续下一段旅程。</p>
          <form className="product-form" onSubmit={send}>
            <label>
              用户名
              <input
                autoComplete="username"
                required
                maxLength={100}
                placeholder="请输入用户名"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              密码
              <div className="password-input">
                <input
                  autoComplete="current-password"
                  type={show ? "text" : "password"}
                  required
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  aria-label={show ? "隐藏密码" : "显示密码"}
                  onClick={() => setShow(!show)}
                >
                  {show ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>
            {error && (
              <div className="form-error" role="alert">
                {error}
              </div>
            )}
            <button
              className="button button-primary login-submit"
              disabled={busy}
            >
              {busy ? (
                <Spinner label="正在登录" />
              ) : (
                <>
                  进入旅行空间
                  <ArrowRight size={17} />
                </>
              )}
            </button>
          </form>
          <div className="login-help">
            <ShieldCheck size={16} />
            <span>账户由平台管理员开通。需要帮助时，请联系管理员。</span>
          </div>
        </div>
        <footer>
          TravelMate <span>让每一程，从容出发</span>
        </footer>
      </section>
    </div>
  );
}
