import { useState } from "react";
import { MessageCircle, Pencil, Search, Trash2 } from "lucide-react";
import type { Conversation } from "../types";
import { Modal, Spinner } from "./ui";

export function ConversationManager({
  conversations,
  currentId,
  onOpen,
  onRename,
  onDelete,
  onClose,
}: {
  conversations: Conversation[];
  currentId: string;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [mode, setMode] = useState<"rename" | "delete" | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const filtered = conversations.filter((c) =>
    `${c.title} ${c.preview}`
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase()),
  );
  function back() {
    setMode(null);
    setSelected(null);
    setError("");
  }
  async function save() {
    if (!selected || busy || (mode === "rename" && !title.trim())) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "rename") await onRename(selected.id, title.trim());
      else await onDelete(selected.id);
      back();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={
        mode === "rename"
          ? "重命名会话"
          : mode === "delete"
            ? "删除会话"
            : "会话管理"
      }
      description={mode ? undefined : "在这里查找、重命名或删除对话。"}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      {selected && mode ? (
        <form
          className="product-form"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          {mode === "rename" ? (
            <label>
              会话名称
              <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={64}
                disabled={busy}
                placeholder="输入一个容易辨认的名称"
                required
              />
              <span className="muted">最多 64 个字符</span>
            </label>
          ) : (
            <div className="conversation-delete-notice">
              <strong>确定删除“{selected.title}”？</strong>
              <p>
                对话将从列表中移除，已生成的订单、行程和服务记录会保留。正在处理或待确认的操作需要先在会话中停止。
              </p>
            </div>
          )}
          {error && (
            <p className="conversation-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-footer">
            <button
              type="button"
              className="button button-secondary"
              onClick={back}
              disabled={busy}
            >
              取消
            </button>
            <button
              type="submit"
              className={`button ${mode === "delete" ? "button-danger" : "button-primary"}`}
              disabled={busy || (mode === "rename" && !title.trim())}
            >
              {busy ? (
                <Spinner label="正在保存" />
              ) : mode === "delete" ? (
                "确认删除"
              ) : (
                "保存名称"
              )}
            </button>
          </div>
        </form>
      ) : (
        <div className="conversation-manager">
          <label className="search-field">
            <Search size={17} />
            <input
              aria-label="搜索会话"
              placeholder="搜索标题或最近消息"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="conversation-list">
            {filtered.map((c) => (
              <div
                className={`conversation-row ${currentId === c.id ? "selected" : ""}`}
                key={c.id}
              >
                <button
                  className="conversation-open"
                  onClick={() => onOpen(c.id)}
                >
                  <MessageCircle size={18} />
                  <span>
                    <strong>{c.title}</strong>
                    <small>
                      {c.message_count
                        ? `${c.message_count} 轮对话 · ${c.preview}`
                        : "还没有消息"}
                    </small>
                  </span>
                  {currentId === c.id && <em>当前</em>}
                </button>
                <div className="conversation-actions">
                  <button
                    className="icon-button"
                    aria-label={`重命名会话：${c.title}`}
                    title="重命名"
                    onClick={() => {
                      setSelected(c);
                      setTitle(c.title);
                      setMode("rename");
                    }}
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    className="icon-button danger-text"
                    aria-label={`删除会话：${c.title}`}
                    title="删除"
                    onClick={() => {
                      setSelected(c);
                      setMode("delete");
                    }}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
            {!filtered.length && (
              <p className="conversation-empty">
                {query.trim()
                  ? "没有匹配的会话，试试其他关键词。"
                  : "还没有保存的对话，发送第一条消息后即可在这里管理。"}
              </p>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
