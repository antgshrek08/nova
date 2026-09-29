// The bell in the title bar: Nova's notification history (app/notify.py),
// and a real system notification for each new one when Nova's window isn't
// the one in front. Phones get the same notifications by push.
import { useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";

const ICON = { reply: "chat", task: "team", homework: "cap", reminder: "cal", needs_you: "bell" };

function ago(at) {
  const s = Date.now() / 1000 - at;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return new Date(at * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
}

export default function Notifications({ enabledDesktop, onOpen }) {
  const [rows, setRows] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const since = useRef(null);
  const boxRef = useRef(null);
  const desktopRef = useRef(enabledDesktop);
  desktopRef.current = enabledDesktop;

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/notifications?limit=50`);
      const data = await res.json();
      const list = data.notifications || [];
      setRows(list);
      setUnread(data.unread || 0);
      // Only notifications that arrived while this window was open raise a
      // system notification; the first load just fills the list.
      if (since.current != null) {
        const fresh = list.filter((n) => n.at > since.current).reverse();
        const away = document.hidden || !document.hasFocus();
        if (away && desktopRef.current && "Notification" in window) {
          if (Notification.permission === "default") Notification.requestPermission().catch(() => {});
          if (Notification.permission === "granted") {
            fresh.forEach((n) => {
              const note = new Notification(n.title, { body: n.body, tag: n.tag, silent: n.kind === "reply" });
              note.onclick = () => { window.electronAPI?.showMainWindow?.(); window.focus(); onOpen?.(n); };
            });
          }
        }
      }
      since.current = Math.max(since.current || 0, data.now || Date.now() / 1000, ...list.map((n) => n.at));
    } catch { /* the engine banner covers a backend that's down */ }
  }, [onOpen]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", esc); };
  }, [open]);

  const post = (path, body) => fetch(`${BACKEND_URL}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && unread) { await post("/notifications/read"); setUnread(0); setRows((r) => r.map((n) => ({ ...n, read: true }))); }
  }

  return (
    <div className="p-bellwrap" ref={boxRef}>
      <button className="p-bell" onClick={toggle} aria-label={unread ? `Notifications, ${unread} new` : "Notifications"} aria-expanded={open} title="Notifications">
        <Icon name="bell" size={15} />
        {unread > 0 && <span className="n">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="p-notes" role="dialog" aria-label="Notifications">
          <div className="hd">
            <b>Notifications</b>
            <span style={{ flex: 1 }} />
            {rows.length > 0 && <button className="p-link" onClick={async () => { await fetch(`${BACKEND_URL}/notifications`, { method: "DELETE" }); setRows([]); }}>Clear all</button>}
          </div>
          <div className="list">
            {rows.length === 0 && <div className="note" style={{ padding: "18px 14px" }}>Nothing yet. Replies, finished team jobs, new homework and reminders show up here, and on your phone if you turn that on.</div>}
            {rows.map((n) => (
              <button key={n.id} className={`row${n.read ? "" : " new"}`} onClick={() => { setOpen(false); onOpen?.(n); }}>
                <Icon name={ICON[n.kind] || "bell"} size={15} />
                <span className="t"><b>{n.title}</b><small>{n.body}</small></span>
                <span className="when">{ago(n.at)}</span>
              </button>
            ))}
          </div>
          <div className="ft"><button className="p-link" onClick={() => { setOpen(false); onOpen?.({ view: "settings:Notifications" }); }}>Notification settings</button></div>
        </div>
      )}
    </div>
  );
}
