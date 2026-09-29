// What the computer lets Nova do. On macOS, using other apps needs two
// switches in System Settings (Accessibility, Screen Recording); this shows
// whether each is on and takes the user straight there. Windows and Linux
// need nothing, so it says so and stays out of the way.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";

const MAC_PANES = {
  accessibility: ["Accessibility", "Lets Nova press buttons and fill in fields in other apps.", "Privacy_Accessibility"],
  screen: ["Screen Recording", "Lets Nova see your screen and other apps' windows.", "Privacy_ScreenCapture"],
};

export default function SystemAccess({ compact = false }) {
  const [status, setStatus] = useState(null);
  const [asked, setAsked] = useState(false);
  const load = useCallback(() => fetch(`${BACKEND_URL}/desktop/status`).then((r) => r.json()).then(setStatus).catch(() => {}), []);
  useEffect(() => {
    load();
    // Switching Nova on happens in System Settings; notice when the user comes back.
    const back = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    return () => { document.removeEventListener("visibilitychange", back); window.removeEventListener("focus", back); };
  }, [load]);

  if (!status) return null;
  const unavailable = Object.values(status.unavailable || {});
  if (status.platform !== "darwin") {
    if (compact && !unavailable.length) return null;
    return (
      <div className="p-sysaccess">
        {unavailable.length
          ? unavailable.map((u) => <p key={u} className="note">{u}</p>)
          : <p className="note"><Icon name="check" size={14} /> Nova can use your screen, mouse, keyboard and other apps here. Nothing to switch on.</p>}
      </div>
    );
  }
  const perms = status.permissions || {};
  const open = (pane) => {
    const url = `x-apple.systempreferences:com.apple.preference.security?${pane}`;
    if (window.electronAPI?.openLink) window.electronAPI.openLink(url); else window.open(url);
  };
  async function allow() {
    setAsked(true);
    await fetch(`${BACKEND_URL}/desktop/permissions/request`, { method: "POST" }).catch(() => {});
    load();
  }
  const allOn = perms.accessibility && perms.screen;
  return (
    <div className="p-sysaccess">
      <p className="note">
        {allOn ? "Nova can use other apps and see your screen." : "To use other apps for you, macOS needs you to switch Nova on twice. You can do it later, too."}
      </p>
      {Object.entries(MAC_PANES).map(([key, [name, what, pane]]) => (
        <div key={key} className="p-row">
          <span>{name}<small>{what}</small></span>
          {perms[key]
            ? <span className="p-status tested"><Icon name="check" size={12} /> On</span>
            : <button className="p-sm" onClick={() => open(pane)}>Open System Settings</button>}
        </div>
      ))}
      {!allOn && (
        <div className="p-acts">
          <button className="p-sm dark" onClick={allow}>{asked ? "Ask again" : "Allow"}</button>
          <button className="p-link" onClick={load}><Icon name="refresh" size={14} />Check again</button>
        </div>
      )}
      {!allOn && asked && <p className="note">In System Settings, find Nova in the list and switch it on. macOS may ask you to reopen Nova afterwards.</p>}
    </div>
  );
}
