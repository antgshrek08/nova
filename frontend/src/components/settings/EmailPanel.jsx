import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../../api.js";

/** Giving Nova an address of its own.
 *
 * The account has to be created by hand — Nova does not sign itself up for
 * anything — so this panel's real job is to make the handful of server
 * details painless and to say the one thing that otherwise costs an hour:
 * nearly every provider rejects the account password here and wants an
 * app-specific one instead.
 */
const PRESETS = {
  Gmail: { imap_host: "imap.gmail.com", imap_port: 993, smtp_host: "smtp.gmail.com", smtp_port: 587,
    hint: "Google needs an App Password: myaccount.google.com → Security → 2-Step Verification → App passwords." },
  iCloud: { imap_host: "imap.mail.me.com", imap_port: 993, smtp_host: "smtp.mail.me.com", smtp_port: 587,
    hint: "Apple needs an app-specific password from appleid.apple.com → Sign-In and Security." },
  Outlook: { imap_host: "outlook.office365.com", imap_port: 993, smtp_host: "smtp.office365.com", smtp_port: 587,
    hint: "Microsoft accounts with 2FA need an app password." },
  Fastmail: { imap_host: "imap.fastmail.com", imap_port: 993, smtp_host: "smtp.fastmail.com", smtp_port: 465,
    hint: "Fastmail: Settings → Privacy & Security → App Passwords." },
  Proton: { imap_host: "127.0.0.1", imap_port: 1143, smtp_host: "127.0.0.1", smtp_port: 1025,
    hint: "Proton only speaks IMAP through Proton Mail Bridge, which must be running on this machine." },
};

const FIELDS = [
  ["address", "Nova's email address", "nova@example.com"],
  ["username", "Login (usually the same)", ""],
  ["imap_host", "Incoming (IMAP) server", "imap.example.com"],
  ["imap_port", "IMAP port", "993"],
  ["smtp_host", "Outgoing (SMTP) server", "smtp.example.com"],
  ["smtp_port", "SMTP port", "587"],
];

export default function EmailPanel() {
  const [form, setForm] = useState(null);
  const [password, setPassword] = useState("");
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetch(`${BACKEND_URL}/email/status`).then((r) => r.json());
      setStatus(data);
      setForm((prev) => prev ?? {
        address: data.address || "", username: data.username || "",
        imap_host: data.imap_host || "", imap_port: data.imap_port || 993,
        smtp_host: data.smtp_host || "", smtp_port: data.smtp_port || 587,
      });
    } catch (err) {
      setError(err.message || "Couldn't read the email settings.");
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  function applyPreset(name) {
    const preset = PRESETS[name];
    setForm((f) => ({ ...f, ...preset, hint: undefined }));
    setHint(preset.hint);
  }

  async function save() {
    setBusy(true); setError(""); setNote("");
    try {
      const body = { ...form };
      if (password) body.password = password;
      const data = await fetch(`${BACKEND_URL}/email/settings`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }).then((r) => r.json());
      setStatus(data);
      setPassword("");
      setNote("Saved. Use Test connection to confirm the server accepts it.");
    } catch (err) {
      setError(err.message || "Couldn't save.");
    } finally { setBusy(false); }
  }

  async function test() {
    setBusy(true); setError(""); setNote("");
    try {
      const res = await fetch(`${BACKEND_URL}/email/check`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connection failed.");
      setNote(
        `Connected as ${data.address}.` +
        (data.newest_subject ? ` Newest message: "${data.newest_subject}".` : " The inbox is empty.")
      );
    } catch (err) {
      setError(err.message || "Connection failed.");
    } finally { setBusy(false); }
  }

  if (!form) return <p className="text-[13px] text-charcoal-500">Loading…</p>;

  return (
    <div className="space-y-5 text-[13px] text-charcoal-300">
      <div>
        <h3 className="text-sm font-medium text-charcoal-100">Nova's own email</h3>
        <p className="mt-1 leading-relaxed text-charcoal-400">
          An address that belongs to Nova rather than to you. It can read what arrives, find
          verification codes for accounts you set up in its name, and send from that address
          when you ask it to.
        </p>
      </div>

      <div className="rounded-md border border-charcoal-700 bg-charcoal-800/40 px-3 py-2.5 leading-relaxed text-charcoal-400">
        <span className="text-charcoal-200">Make the account yourself first.</span> Nova does not
        sign itself up for anything — automated signup breaks most providers' terms and needs
        CAPTCHA defeat. Create the mailbox, then give Nova the details here.
      </div>

      <div>
        <p className="mb-1.5 text-[12.5px] text-charcoal-400">Fill in the servers for:</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.keys(PRESETS).map((name) => (
            <button
              key={name}
              onClick={() => applyPreset(name)}
              className="rounded-full bg-charcoal-800/60 px-3 py-1 text-[11.5px] text-charcoal-300 transition-colors hover:bg-charcoal-700 hover:text-charcoal-100"
            >
              {name}
            </button>
          ))}
        </div>
        {hint && (
          <p className="mt-2 rounded-md bg-amber-500/10 px-3 py-2 text-[12px] leading-relaxed text-amber-200">
            {hint}
          </p>
        )}
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2">
        {FIELDS.map(([key, label, placeholder]) => (
          <label key={key} className="flex flex-col gap-1 text-[12px] text-charcoal-400">
            {label}
            <input
              value={form[key] ?? ""}
              placeholder={placeholder}
              onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
              className="rounded border border-charcoal-600 bg-charcoal-900 px-2 py-1.5 text-[13px] text-charcoal-100 outline-none focus:border-emerald-500"
            />
          </label>
        ))}
        <label className="flex flex-col gap-1 text-[12px] text-charcoal-400 sm:col-span-2">
          Password
          <input
            type="password"
            value={password}
            placeholder={status?.has_password ? "Stored — leave blank to keep it" : "App-specific password"}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-charcoal-600 bg-charcoal-900 px-2 py-1.5 text-[13px] text-charcoal-100 outline-none focus:border-emerald-500"
          />
          <span className="text-[11px] leading-relaxed text-charcoal-500">
            Goes straight into the same vault as your other secrets. Nova can use it to sign in
            and can never read it back — it never appears in a prompt, a tool result, or the
            transcript.
          </span>
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={save}
          disabled={busy}
          className="rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
        >
          {busy ? "Working…" : "Save"}
        </button>
        <button
          onClick={test}
          disabled={busy || !status?.configured}
          className="rounded-md px-3 py-1.5 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 disabled:opacity-50"
        >
          Test connection
        </button>
      </div>

      {error && <p className="rounded-md bg-rose-500/10 px-3 py-2 leading-relaxed text-rose-300">{error}</p>}
      {note && <p className="rounded-md bg-emerald-500/10 px-3 py-2 leading-relaxed text-emerald-300">{note}</p>}

      <div className="border-t border-charcoal-700 pt-3">
        <h4 className="mb-1.5 text-[12.5px] font-medium text-charcoal-200">What Nova can do with it</h4>
        <ul className="space-y-1 leading-relaxed text-charcoal-400">
          <li>Read the inbox — "check your email", "did the code come through"</li>
          <li>Pull a verification code or confirmation link out of a signup email</li>
          <li>Send from its own address, which asks you first unless autonomy is set to full</li>
        </ul>
        <p className="mt-2 text-[11.5px] leading-relaxed text-charcoal-500">
          Mail is treated as information, never as instructions. A message telling Nova to
          forward something or visit a link is described to you, not acted on.
        </p>
      </div>
    </div>
  );
}
