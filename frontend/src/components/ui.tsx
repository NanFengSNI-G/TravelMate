import { useEffect, useRef, type ReactNode } from "react";
import { X, ArrowUpRight, Map, LoaderCircle, Sparkles } from "lucide-react";
import { statusLabels } from "../lib";
export function Brand({ light = false }: { light?: boolean }) {
  return (
    <div className={`brand ${light ? "brand-light" : ""}`}>
      <span className="brand-mark">
        <Map size={23} strokeWidth={1.7} />
      </span>
      <div>
        TravelMate<span className="brand-caption">让每一程，从容出发</span>
      </div>
    </div>
  );
}
export function Badge({
  status,
  children,
}: {
  status?: string;
  children?: ReactNode;
}) {
  const kind =
    status && ["WAITING", "VERIFIED", "OPEN"].includes(status)
      ? "amber"
      : status && ["FAILED", "REVOKED"].includes(status)
        ? "red"
        : status && ["CANCELLED", "CLOSED"].includes(status)
          ? "neutral"
          : "green";
  return (
    <span className={`badge badge-${kind}`}>
      <i />
      {children || (status && statusLabels[status]) || status}
    </span>
  );
}
export function Spinner({ label = "加载中" }: { label?: string }) {
  return (
    <span className="spinner" role="status">
      <LoaderCircle className="spin" size={17} />
      <span>{label}</span>
    </span>
  );
}
export function Empty({
  icon,
  title,
  text,
  action,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action && (
        <button className="button button-primary" onClick={onAction}>
          {action}
          <ArrowUpRight size={16} />
        </button>
      )}
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  text,
  children,
}: {
  eyebrow?: string;
  title: string;
  text?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {text && <p>{text}</p>}
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
export function Modal({
  title,
  description,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focus = () =>
      box.current
        ?.querySelector<HTMLElement>(
          'input,button,textarea,select,[tabindex="0"]',
        )
        ?.focus();
    focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab") {
        const nodes = box.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]',
        );
        if (!nodes?.length) return;
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = original;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? "modal-wide" : ""}`}
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-heading">
          <div>
            <h2 id="modal-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="关闭弹窗"
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function AssistantAvatar() {
  return (
    <span className="assistant-avatar">
      <Sparkles size={17} />
    </span>
  );
}
export function Skeleton() {
  return (
    <div className="skeleton-grid" aria-label="正在加载内容">
      {[1, 2, 3].map((i) => (
        <div className="skeleton-card" key={i}>
          <div />
          <div />
          <div />
        </div>
      ))}
    </div>
  );
}
