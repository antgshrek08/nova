import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../../api.js";

/** Reaching this Nova from somewhere that isn't this machine.
 *
 * Loopback has always been the whole security model (see backend/app/
 * access.py) — everything past it, run_command included, is unguarded. This
 * panel is the one place that model can be widened, so it only runs on this
 * machine to begin with (the backend refuses /access/phone and /access/token
 * from anywhere else too, but a control that offers a button it would then
 * refuse is its own kind of broken).
 */
export default function AccessPanel() {
  const [status, setStatus] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [addresses, setAddresses] = useState([]);
  const [tailscaleUrl, setTailscaleUrl] = useState(null);
  const [links, setLinks] = useState([]);
  const [restartRequired, setRestartRequired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState("");

  const refresh = useCallback(async () => {
    try {
      const result = await fetch(`${BACKEND_URL}/access/status`).then((r) => r.json());
      setStatus(result);
      setEnabled(Boolean(result.phone_access_enabled));
      setAddresses(result.addresses || []);
      setTailscaleUrl(result.tailscale_https_url || null);
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function setPhoneAccess(next) {
    setBusy(true); setError(""); setNote(""); setCopied("");
    try {
      const result = await fetch(`${BACKEND_URL}/access/phone`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      }).then((r) => r.json());
      setEnabled(result.enabled);
      setAddresses(result.addresses || []);
      setTailscaleUrl(result.tailscale_https_url || null);
      setLinks(result.links || []);
      setRestartRequired(Boolean(result.restart_required));
      setNote(
        next
          ? (result.links || []).length
            ? "Restart Nova, then open one of the links below on your phone — once."
            : "Restart Nova. No address was found yet to reach this machine on; reopen this panel after restarting."
          : "Phone access is off. Restart Nova for it to stop listening beyond this machine."
      );
      await refresh();
    } catch (err) {
      setError(err.message || "Couldn't change this.");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink(link) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(link);
    } catch {
      setError("Couldn't copy — select and copy the link by hand.");
    }
  }

  async function rotateToken() {
    setBusy(true); setError(""); setNote(""); setCopied("");
    try {
      await fetch(`${BACKEND_URL}/access/token?rotate=true`, { method: "POST" });
      setNote("New token issued. Every link and device using the old one stops working — turn phone access off and back on to get fresh links.");
      await refresh();
    } catch (err) {
      setError(err.message || "Couldn't rotate the token.");
    } finally {
      setBusy(false);
    }
  }


  return (
    <div className="space-y-5 text-[13px] text-charcoal-300">
      <div>
        <h3 className="text-sm font-medium text-charcoal-100">Reach Nova from your phone</h3>
        <p className="mt-1 leading-relaxed text-charcoal-400">
          Off by default: this machine's own loopback connection is what keeps Nova safe today, since
          nothing past it needs a password. Turning this on lets a device that presents the right
          token in — from your home network, or from anywhere at all if this machine has Tailscale
          running.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setPhoneAccess(!enabled)}
          disabled={busy}
          className={
            enabled
              ? "rounded-md px-3 py-1.5 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 disabled:opacity-50"
              : "rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
          }
        >
          {busy ? "Working…" : enabled ? "Turn off phone access" : "Turn on phone access"}
        </button>
        <button
          onClick={rotateToken}
          disabled={busy}
          className="rounded-md px-3 py-1.5 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 disabled:opacity-50"
        >
          Issue a new token
        </button>
      </div>

      {error && <p className="rounded-md bg-rose-500/10 px-3 py-2 text-rose-300">{error}</p>}
      {note && <p className="rounded-md bg-emerald-500/10 px-3 py-2 text-emerald-300">{note}</p>}

      {links.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[12.5px] font-medium text-charcoal-200">Open one of these on your phone, once</h4>
          <ul className="space-y-1.5">
            {links.map((link) => {
              const isSecureAnywhere = tailscaleUrl && link.startsWith(`${tailscaleUrl}/`);
              return (
                <li key={link} className="flex items-center justify-between gap-3 rounded-md bg-charcoal-800/50 px-2.5 py-2">
                  <div className="min-w-0">
                    <span className="block truncate font-mono text-[11.5px] text-charcoal-200">{link}</span>
                    <span className="text-[11px] text-charcoal-500">
                      {isSecureAnywhere
                        ? "Tailscale, HTTPS — works from anywhere, and voice works over this one"
                        : "This Wi-Fi network only, and plain http:// — voice won't work over this one"}
                    </span>
                  </div>
                  <button
                    onClick={() => copyLink(link)}
                    className="shrink-0 rounded px-2 py-1 text-[11.5px] text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800"
                  >
                    {copied === link ? "Copied" : "Copy"}
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="mt-1.5 text-[11px] text-charcoal-500">
            The token in the link is saved on your phone and removed from the address bar the moment it opens — it isn't left sitting in a URL.
          </p>
        </div>
      )}

      {restartRequired && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 leading-relaxed text-amber-200">
          This takes effect at Nova's next restart — the port it listens on is fixed for the life of the running app.
        </p>
      )}

      {enabled && !tailscaleUrl && (
        <p className="rounded-md border border-charcoal-600 px-3 py-2.5 leading-relaxed text-charcoal-400">
          No Tailscale HTTPS address found on this machine — links below only work over the same Wi-Fi,
          and voice won't work over them (a browser needs a secure connection for the microphone). Install
          Tailscale, sign in, then run <code className="font-mono">tailscale serve --bg http://127.0.0.1:8000</code> once
          on this machine to get an HTTPS link that works from anywhere.
        </p>
      )}

      {enabled && links.length === 0 && (
        <p className="rounded-md border border-charcoal-600 px-3 py-2.5 leading-relaxed text-charcoal-400">
          Phone access is on, but the link carries the token and this page doesn't keep it after you
          navigate away. Turn it off and back on to get a fresh link.
        </p>
      )}

      {status && !enabled && (
        <p className="border-t border-charcoal-700 pt-3 text-[12px] leading-relaxed text-charcoal-500">
          {status.note}
        </p>
      )}
    </div>
  );
}
