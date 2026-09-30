// Settings > Remote: using Nova from your phone (or another computer), like a
// remote session. On the computer Nova runs on: set up the secure address
// once, then add each device -- each gets its own key and can be removed on
// its own. On the phone: which computer it's connected to, and whether that
// Nova is open right now.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL, setAccessToken } from "../api.js";
import Icon from "./icons.jsx";
import { IS_REMOTE, agoText, checkSession, useSession } from "./remote.js";
import { useUi } from "./ui.jsx";

const openLink = (url) => (window.electronAPI?.openLink ? window.electronAPI.openLink(url) : window.open(url, "_blank"));

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

function Step({ n, done, title, children, action }) {
  return (
    <div className={`p-pstep${done ? " done" : ""}`}>
      <span className="num">{done ? <Icon name="check" size={14} /> : n}</span>
      <div className="body"><b>{title}</b>{children && <div className="note">{children}</div>}</div>
      {!done && action}
    </div>
  );
}

export default function RemoteSettings() {
  return IS_REMOTE ? <ThisDevice /> : <OnTheComputer />;
}

function ThisDevice() {
  const session = useSession();
  const ui = useUi();
  const [me, setMe] = useState(null);
  useEffect(() => { if (session.live) call("/remote/me").then(setMe).catch(() => {}); }, [session.live]);
  const forget = async () => {
    const yes = await ui.confirm({ title: "Disconnect this device?", body: "It stops reaching your computer's Nova. You'd need a new setup link from Settings > Remote on the computer to connect again.", confirm: "Disconnect", danger: true });
    if (!yes) return;
    setAccessToken(null);
    window.location.reload();
  };
  return (
    <div className="p-sgroup">
      <div className="p-shead"><h4>This device</h4></div>
      <div className="p-remote-card">
        <span className={`dot${session.live ? " on" : ""}`} />
        <div className="t">
          <b>{session.live ? `Connected to ${me?.computer || session.name || "your computer"}` : session.configured ? "Your computer's Nova isn't reachable" : "Not set up"}</b>
          <small>{session.live ? `As ${me?.device || "this device"} · checked ${agoText(session.checkedAt)}`
            : session.configured ? "Open Nova on your computer, and make sure Tailscale is on here and there." : "Open Settings > Remote on your computer and add this device."}</small>
        </div>
        <button className="p-sm" disabled={session.checking} onClick={checkSession}>{session.checking ? "Searching…" : "Search now"}</button>
      </div>
      <p className="d">Chat, starting agents and Nova's help in Studio run on your computer, so they need Nova open there. Memory, Academics and your agents' status stay here from the last time you were connected.</p>
      {session.configured && <div className="p-acts"><button className="p-sm danger" onClick={forget}>Disconnect this device</button></div>}
    </div>
  );
}

function OnTheComputer() {
  const ui = useUi();
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState("");
  const [name, setName] = useState("");
  const [added, setAdded] = useState(null);

  const load = useCallback(async () => {
    try { setS(await call("/remote/devices")); } catch (e) { setS({ error: e.message }); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  async function serve() {
    setBusy("serve");
    try {
      await call("/access/phone-setup/serve", { method: "POST" });
      ui.toast("Nova now has a secure address on your Tailscale network.");
      await load();
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }

  async function add(e) {
    e.preventDefault();
    setBusy("add");
    try {
      setAdded(await call("/remote/devices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name || "My phone" }) }));
      setName("");
      await load();
    } catch (err) { ui.toast(err.message, { error: true }); } finally { setBusy(""); }
  }

  async function remove(d) {
    const yes = await ui.confirm({ title: `Remove ${d.name}?`, body: "It can't reach this Nova any more. Your other devices keep working.", confirm: "Remove", danger: true });
    if (!yes) return;
    try { await call(`/remote/devices/${d.id}`, { method: "DELETE" }); ui.toast(`${d.name} removed.`); if (added?.device?.id === d.id) setAdded(null); load(); }
    catch (e) { ui.toast(e.message, { error: true }); }
  }

  if (!s) return <div className="note">Checking this computer…</div>;
  if (s.error) return <p className="err">{s.error}</p>;
  const setup = s.setup || {};
  const ready = Boolean(setup.https_url && setup.serving_nova);
  const again = <button className="p-sm" onClick={load}><Icon name="refresh" />Check again</button>;

  return (
    <>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Use Nova from your phone</h4></div>
        <p className="d">Like a remote session: your phone shows this computer's Nova. It's free (no App Store needed) and private -- only your own devices, signed in to your Tailscale, can reach it. Chat and starting agents work while Nova is open here; Memory, Academics and agents' status stay on the phone.</p>
        {!ready && (
          <div className="p-psteps">
            <Step n={1} done={setup.tailscale_installed} title="Install Tailscale on this computer"
              action={<><button className="p-sm dark" onClick={() => openLink("https://tailscale.com/download")}>Get Tailscale</button>{again}</>}>
              It makes a private network between your own devices. Nothing is opened to the internet.
            </Step>
            <Step n={2} done={setup.signed_in} title="Sign in to Tailscale" action={again}>Open Tailscale and sign in with Google, Microsoft, Apple or GitHub.</Step>
            <Step n={3} done={setup.serving_nova} title="Give Nova a secure address"
              action={<button className="p-sm dark" onClick={serve} disabled={busy === "serve" || !setup.signed_in}>{busy === "serve" ? "Setting up…" : "Set it up"}</button>}>
              One click. If it asks, turn on HTTPS for your network at login.tailscale.com, under DNS.
            </Step>
          </div>
        )}
        {ready && <div className="p-row"><span>Nova's secure address<small className="mono">{s.address}</small></span><div className="ctl"><span className="p-status tested"><Icon name="check" size={12} /> Ready</span></div></div>}
      </div>

      <div className="p-sgroup">
        <div className="p-shead"><h4>Your devices</h4></div>
        {(s.devices || []).length === 0 && <p className="d">None yet. Add your phone below.</p>}
        {(s.devices || []).map((d) => (
          <div className="p-row" key={d.id}>
            <span>{d.name}<small>{d.last_seen ? `Last used ${agoText(d.last_seen * 1000)}` : "Not used yet"} · added {agoText(d.created_at * 1000)}</small></span>
            <div className="ctl"><button className="p-sm danger" onClick={() => remove(d)}>Remove</button></div>
          </div>
        ))}
        <form className="p-inline" onSubmit={add}>
          <input className="p-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Device name, like Anna's iPhone" maxLength={40} aria-label="Device name" />
          <button className="p-sm dark" disabled={!ready || busy === "add"}>{busy === "add" ? "Adding…" : "Add a device"}</button>
        </form>
        {!ready && <p className="note">Finish the steps above first.</p>}
        {added && (
          <div className="p-phone">
            <div className="qr" role="img" aria-label="QR code of the setup link" dangerouslySetInnerHTML={{ __html: added.qr_svg }} />
            <ol>
              <li>On {added.device.name}, install <b>Tailscale</b> and sign in with the same account.</li>
              <li>Point its camera at this code and open the link. The key is saved on that device only.</li>
              <li>iPhone: <b>Share</b>, then <b>Add to Home Screen</b>. Android: browser menu, then <b>Install app</b>.</li>
              <li>Open Nova from the new icon. Turn on notifications in its Settings if you want them.</li>
            </ol>
            <div className="p-acts" style={{ gridColumn: "1 / -1" }}>
              <button className="p-sm" onClick={() => navigator.clipboard.writeText(added.link).then(() => ui.toast("Copied. It holds this device's key, so only send it to yourself."))}><Icon name="copy" />Copy setup link</button>
              <button className="p-sm" onClick={() => setAdded(null)}>Done</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
