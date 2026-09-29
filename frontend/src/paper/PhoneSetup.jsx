// Settings > Phone access: a guide any user can follow to put Nova on their
// phone for free. Nova's phone app is the web app it already serves; it
// installs from the phone's browser (no App Store or Play Store) and reaches
// only the user's own computer, over their private Tailscale network. Every
// step is checked live by the engine (access.phone_readiness).
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";
import { useUi } from "./ui.jsx";

const openLink = (url) => (window.electronAPI?.openLink ? window.electronAPI.openLink(url) : window.open(url, "_blank"));

function Step({ n, done, title, children, action }) {
  return (
    <div className={`p-pstep${done ? " done" : ""}`}>
      <span className="num">{done ? <Icon name="check" size={14} /> : n}</span>
      <div className="body"><b>{title}</b>{children && <div className="note">{children}</div>}</div>
      {!done && action}
    </div>
  );
}

export default function PhoneSetup() {
  const ui = useUi();
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  const [devices, setDevices] = useState([]);
  const check = useCallback(async () => {
    try {
      setS(await fetch(`${BACKEND_URL}/access/phone-setup`).then((r) => r.json()));
      setDevices(await fetch(`${BACKEND_URL}/push/devices`).then((r) => r.json()).then((d) => (Array.isArray(d) ? d : [])));
    } catch { setS({ error: true }); }
  }, []);
  useEffect(() => { check(); }, [check]);

  async function serve() {
    setBusy(true);
    try {
      const res = await fetch(`${BACKEND_URL}/access/phone-setup/serve`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Couldn't set it up.");
      ui.toast("Nova now has a secure address on your Tailscale network.");
      await check();
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(false); }
  }

  const again = <button className="p-sm" onClick={check}><Icon name="refresh" />Check again</button>;
  if (!s) return <div className="note">Checking this computer…</div>;
  if (s.error) return <p className="err">Couldn't reach Nova's engine.</p>;

  return (
    <div className="p-sgroup">
      <div className="p-shead"><h4>Nova on your phone</h4></div>
      <p className="d">Free, with no App Store or Play Store. Nova's phone app installs from your phone's browser and talks only to this computer, over a private network that only your devices are on (Tailscale, free for personal use).</p>
      <div className="p-psteps">
        <Step n={1} done={s.tailscale_installed} title="Install Tailscale on this computer"
          action={<><button className="p-sm dark" onClick={() => openLink("https://tailscale.com/download")}>Get Tailscale</button>{again}</>}>
          It makes a private network between your own devices. Nothing is opened to the internet.
        </Step>
        <Step n={2} done={s.signed_in} title="Sign in to Tailscale on this computer"
          action={again}>
          Open Tailscale from the taskbar and sign in with Google, Microsoft, Apple or GitHub.
        </Step>
        <Step n={3} done={s.serving_nova} title="Give Nova a secure address"
          action={<button className="p-sm dark" onClick={serve} disabled={busy || !s.signed_in}>{busy ? "Setting up…" : "Set it up"}</button>}>
          One click. Only devices signed in to your Tailscale can reach it. If it asks, turn on HTTPS for your network at login.tailscale.com, DNS.
        </Step>
        <Step n={4} done={devices.length > 0} title="Put Nova on your phone"
          action={null}>
          {s.ready ? "Follow the steps next to the code below." : "Finish the steps above first."}
        </Step>
      </div>
      {s.ready && (
        <div className="p-phone">
          <div className="qr" role="img" aria-label="QR code of your phone setup link" dangerouslySetInnerHTML={{ __html: s.qr_svg }} />
          <ol>
            <li>On your phone, install <b>Tailscale</b> from the App Store or Play Store and sign in with the same account.</li>
            <li>Point the phone's camera at this code and open the link. It signs the phone in to Nova once; the key stays on the phone.</li>
            <li>iPhone: tap <b>Share</b>, then <b>Add to Home Screen</b>. Android: open the browser menu, then <b>Install app</b>.</li>
            <li>Open Nova from the new icon, go to Settings, Notifications, and turn them on for the phone.</li>
          </ol>
          <div className="p-acts" style={{ gridColumn: "1 / -1" }}>
            <button className="p-sm" onClick={() => navigator.clipboard.writeText(s.link).then(() => ui.toast("Copied. It contains your key, so only send it to yourself."))}><Icon name="copy" />Copy setup link</button>
            {again}
          </div>
        </div>
      )}
      <div className="p-row">
        <span>Phones with notifications<small>{devices.length ? devices.map((d) => d.label || "Phone").join(", ") : "None yet"}</small></span>
        <div className="ctl"><span className={`p-status ${devices.length ? "tested" : "browse"}`}>{devices.length}</span></div>
      </div>
    </div>
  );
}
