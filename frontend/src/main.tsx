import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { api, followRun } from "./api";
import "./style.css";
type Data = Record<string, any>;
function App() {
  const [token, setToken] = useState("");
  const [role, setRole] = useState("");
  const [name, setName] = useState("alice");
  const [password, setPassword] = useState("tutorial123");
  const [cid, setCid] = useState("");
  const [tab, setTab] = useState("服务");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [intent, setIntent] = useState("policy");
  const [text, setText] = useState("标准房取消需要多少钱？");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [people, setPeople] = useState(1);
  const [budget, setBudget] = useState(6000);
  const [ids, setIds] = useState("hotel-0");
  const [orderId, setOrderId] = useState("");
  const [planId, setPlanId] = useState("");
  const [run, setRun] = useState<Data | null>(null);
  const [events, setEvents] = useState<Data[]>([]);
  const [rows, setRows] = useState<Data[]>([]);
  const [natural, setNatural] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [metadata, setMetadata] = useState(
    JSON.stringify(
      {
        document: "hotel-standard",
        supplier: "演示酒店",
        product: "standard",
        valid_from: "2031-01-01",
        valid_to: "2099-12-31",
        rules: { cancel_fee_cents: 6000 },
      },
      null,
      2,
    ),
  );
  async function safe(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function login() {
    await safe(async () => {
      const r = await api("/api/login", "", { name, password });
      setToken(r.token);
      setRole(r.user.role);
      setCid((await api("/api/conversations", r.token, {})).id);
    });
  }
  async function watch(id: string) {
    await followRun(id, token, (e) => setEvents((old) => [...old, e]));
    setRun(await api(`/api/runs/${id}`, token));
  }
  async function submit(request?: Data) {
    await safe(async () => {
      setEvents([]);
      setRun(null);
      const req = request || {
        intent,
        question: text,
        start: start || null,
        end: end || null,
        people,
        budget_cents: Math.round(budget * 100),
        resource_ids: ids
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        order_id: orderId || null,
        plan_id: planId || null,
      };
      const r = await api(`/api/conversations/${cid}/messages`, token, {
        text,
        request: natural && !request ? null : req,
      });
      await watch(r.run_id);
    });
  }
  async function propose(path: string, body: Data) {
    const queued = await api(path, token, body);
    setTab("服务");
    setEvents([]);
    setRun(null);
    await watch(queued.run_id);
  }
  async function approve(decision: string) {
    await safe(async () => {
      await api(`/api/runs/${run!.id}/approval`, token, {
        decision,
        version: run!.result.approval.proposal.version,
      });
      await watch(run!.id);
    });
  }
  async function refresh(which: string) {
    await safe(async () => {
      setRows(await api(which, token));
    });
  }
  const outcome = run?.result;
  return (
    <main>
      <header>
        <h1>TravelMate</h1>
        <span>演示供应商 · 机票与酒店金额，不含支付</span>
      </header>
      {!token ? (
        <section>
          <h2>登录</h2>
          <label>
            用户名
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button onClick={login}>登录</button>
          <p>教学账户：alice、bob、admin</p>
        </section>
      ) : (
        <>
          <nav>
            {[
              "服务",
              "订单",
              "工单",
              ...(role === "admin" ? ["知识管理"] : []),
            ].map((t) => (
              <button
                key={t}
                onClick={() => {
                  setTab(t);
                  setRows([]);
                }}
              >
                {t}
              </button>
            ))}
            <button
              onClick={() =>
                safe(async () => {
                  setCid((await api("/api/conversations", token, {})).id);
                  setRun(null);
                  setEvents([]);
                })
              }
            >
              新会话
            </button>
          </nav>
          {tab === "服务" && (
            <>
              <section>
                <h2>提出需求</h2>
                <label>
                  业务
                  <select
                    value={intent}
                    onChange={(e) => setIntent(e.target.value)}
                  >
                    {[
                      "policy",
                      "search",
                      "plan",
                      "book",
                      "change",
                      "cancel",
                      "support",
                      "repair",
                    ].map((i, n) => (
                      <option key={i} value={i}>
                        {
                          [
                            "政策咨询",
                            "资源查询",
                            "行程规划",
                            "预订",
                            "订单变更",
                            "取消",
                            "人工服务",
                            "复杂修复",
                          ][n]
                        }
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  问题
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={natural}
                    onChange={(e) => setNatural(e.target.checked)}
                  />
                  真实模型解析自然语言（需后端 live 配置）
                </label>
                <div className="grid">
                  <label>
                    出发/入住
                    <input
                      type="date"
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </label>
                  <label>
                    退房
                    <input
                      type="date"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </label>
                  <label>
                    人数
                    <input
                      type="number"
                      min="1"
                      max="6"
                      value={people}
                      onChange={(e) => setPeople(+e.target.value)}
                    />
                  </label>
                  <label>
                    预算（元）
                    <input
                      type="number"
                      value={budget}
                      onChange={(e) => setBudget(+e.target.value)}
                    />
                  </label>
                </div>
                <label>
                  选择的资源 ID（逗号分隔）
                  <input value={ids} onChange={(e) => setIds(e.target.value)} />
                </label>
                <label>
                  已有订单 ID
                  <input
                    value={orderId}
                    onChange={(e) => setOrderId(e.target.value)}
                  />
                </label>
                <label>
                  已有方案 ID
                  <input
                    value={planId}
                    onChange={(e) => setPlanId(e.target.value)}
                  />
                </label>
                <button disabled={busy} onClick={() => submit()}>
                  提交
                </button>
                <button onClick={() => refresh("/api/resources")}>
                  查看演示资源和日期
                </button>
                {rows.map((r) => (
                  <article key={r.id}>
                    {r.name} · {r.id} · ¥{r.price / 100}
                    <p>{JSON.stringify(r.details)}</p>
                  </article>
                ))}
              </section>
              {run && (
                <section>
                  <h2>处理结果 · {run.status}</h2>
                  <button
                    onClick={() =>
                      safe(async () => {
                        await api(`/api/runs/${run.id}/cancel`, token, {});
                        setRun(await api(`/api/runs/${run.id}`, token));
                      })
                    }
                  >
                    停止后续任务
                  </button>
                  {run.error && <p className="error">{run.error}</p>}
                  {outcome?.approval && (
                    <article>
                      <h3>待确认操作</h3>
                      <p>
                        确认前请检查将新增或修改的内容、日期、费用和条款。拒绝后可修改需求提交新提案。
                      </p>
                      <pre>
                        {JSON.stringify(
                          outcome.approval.proposal.actions,
                          null,
                          2,
                        )}
                      </pre>
                      <button
                        disabled={busy}
                        onClick={() => approve("approve")}
                      >
                        确认执行
                      </button>
                      <button disabled={busy} onClick={() => approve("reject")}>
                        拒绝
                      </button>
                      <EvidenceList
                        evidence={outcome.approval.proposal.evidence}
                      />
                    </article>
                  )}
                  {outcome?.evidence && (
                    <>
                      <p>证据状态：{outcome.evidence.status}</p>
                      <EvidenceList evidence={outcome.evidence.evidence} />
                    </>
                  )}
                  {outcome?.plan && (
                    <>
                      <p>方案 ID：{outcome.plan.id}</p>
                      {outcome.plan.options.map((o: Data) => (
                        <article key={o.label}>
                          <h3>{o.label}</h3>
                          <p>
                            ¥{o.amount / 100} · {o.scope}
                          </p>
                          <button
                            onClick={() =>
                              submit({
                                intent: "book",
                                start: o.start,
                                end: o.end,
                                people: o.people,
                                resource_ids: o.resource_ids,
                              })
                            }
                          >
                            选此方案并查看报价
                          </button>
                          <EvidenceList evidence={o.evidence.evidence} />
                        </article>
                      ))}
                    </>
                  )}
                  {outcome?.repair && (
                    <>
                      <h3>修复方案</h3>
                      {outcome.repair.options.map((o: Data) => (
                        <article key={o.label}>
                          <b>{o.label}</b>
                          <p>{o.explanation}</p>
                          <button
                            onClick={() =>
                              submit({
                                intent: "book",
                                start: o.start,
                                end: o.end,
                                people,
                                resource_ids: o.resource_ids,
                              })
                            }
                          >
                            查看替代资源预订提案
                          </button>
                        </article>
                      ))}
                      <p>
                        已有订单需单独变更或取消；选择替代资源不自动取消原订单。
                      </p>
                    </>
                  )}
                  {outcome?.operations &&
                    outcome.operations.map((o: Data, n: number) => (
                      <article key={n}>
                        {o.status} · {o.order ? `订单 ${o.order}` : "业务变更"}
                        <p>{o.message}</p>
                      </article>
                    ))}
                  {outcome?.case_id && <p>已创建工单 {outcome.case_id}</p>}
                  <details>
                    <summary>结果详情</summary>
                    <pre>{JSON.stringify(outcome, null, 2)}</pre>
                  </details>
                </section>
              )}
              <section>
                <h2>任务进度</h2>
                {events.map((e, n) => (
                  <details key={n}>
                    <summary>
                      {e.sequence} · {e.type}
                    </summary>
                    <pre>{JSON.stringify(e.payload, null, 2)}</pre>
                  </details>
                ))}
              </section>
            </>
          )}
          {tab === "订单" && (
            <section>
              <h2>本人订单</h2>
              <button onClick={() => refresh("/api/orders")}>刷新</button>
              {rows.map((o) => (
                <article key={o.id}>
                  <b>
                    {o.resource} · {o.status}
                  </b>
                  <p>
                    订单 {o.id} · ¥{o.amount / 100}
                  </p>
                  <button
                    onClick={() => {
                      setOrderId(o.id);
                      setIntent("cancel");
                      setTab("服务");
                    }}
                  >
                    查看取消提案
                  </button>
                  <button
                    onClick={() => {
                      setOrderId(o.id);
                      setIntent("change");
                      setTab("服务");
                    }}
                  >
                    选择替代资源改签
                  </button>
                </article>
              ))}
            </section>
          )}
          {tab === "工单" && (
            <section>
              <h2>人工工单</h2>
              <button onClick={() => refresh("/api/cases")}>刷新</button>
              {rows.map((c) => (
                <article key={c.id}>
                  <b>
                    {c.id} · {c.status}
                  </b>
                  <pre>{JSON.stringify(c.context, null, 2)}</pre>
                  {c.replies.map((r: Data, n: number) => (
                    <p key={n}>
                      {r.by}：{r.text}
                    </p>
                  ))}
                  {role === "admin" && (
                    <>
                      <button
                        onClick={() =>
                          safe(async () => {
                            await propose(`/api/cases/${c.id}/claim`, {});
                          })
                        }
                      >
                        领取
                      </button>
                      <button
                        onClick={() => {
                          const text = prompt("回复内容");
                          if (text)
                            safe(async () => {
                              await propose(`/api/cases/${c.id}/reply`, {
                                text,
                                close: true,
                              });
                            });
                        }}
                      >
                        回复并关闭
                      </button>
                    </>
                  )}
                </article>
              ))}
            </section>
          )}
          {tab === "知识管理" && (
            <section>
              <h2>知识入库与发布</h2>
              <input
                type="file"
                accept=".md,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
              <label>
                文档元数据
                <textarea
                  rows={8}
                  value={metadata}
                  onChange={(e) => setMetadata(e.target.value)}
                />
              </label>
              <button
                onClick={() =>
                  safe(async () => {
                    if (!file) throw Error("请选择文件");
                    const bytes = new Uint8Array(await file.arrayBuffer());
                    let raw = "";
                    for (const b of bytes) raw += String.fromCharCode(b);
                    await propose("/api/knowledge/import", {
                      name: file.name,
                      content_base64: btoa(raw),
                      metadata: JSON.parse(metadata),
                    });
                  })
                }
              >
                导入并核验
              </button>
              <button onClick={() => refresh("/api/knowledge/revisions")}>
                刷新版本
              </button>
              {rows.map((r) => (
                <article key={r.id}>
                  {r.document} · {r.status}
                  <p>
                    {r.valid_from} 至 {r.valid_to}
                  </p>
                  <button
                    onClick={() =>
                      safe(async () => {
                        await propose(`/api/knowledge/${r.id}/publish`, {});
                          })
                    }
                  >
                    发布
                  </button>
                  <button
                    onClick={() =>
                      safe(async () => {
                        await propose(`/api/knowledge/${r.id}/revoke`, {});
                          })
                    }
                  >
                    撤回
                  </button>
                  <button
                    onClick={() =>
                      safe(async () => {
                        await propose(`/api/knowledge/${r.id}/rollback`, {});
                          })
                    }
                  >
                    回滚到此版本
                  </button>
                </article>
              ))}
            </section>
          )}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {busy && <p>处理中，请等待任务结果…</p>}
    </main>
  );
}
function EvidenceList({ evidence }: { evidence: Data[] }) {
  return (
    <>
      {(evidence || []).map((e) => (
        <details key={e.node_id}>
          <summary>
            {e.source} · {e.section}
          </summary>
          <p>{e.text}</p>
          <small>
            证据 {e.node_id} · 版本 {e.revision_id}
          </small>
        </details>
      ))}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
