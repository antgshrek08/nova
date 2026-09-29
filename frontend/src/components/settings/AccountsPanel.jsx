import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../../api.js";

const BLANK = { service: "", username: "", url: "", email: "", password: "", notes: "" };

/** Accounts the user set up in Nova's name.
 *
 * The password field here is the only one that behaves differently from the
 * rest of the form, and the copy has to earn that: it goes to the same vault
 * as the other secrets, Nova can type it and never read it, and it is not
 * shown again afterwards. Everything else on this screen is ordinary metadata
 * and is deliberately plain, because the list is meant to be readable at a
 * glance -- "which sites does Nova already have a login for" is the question
 * it exists to answer.
 */
export default function AccountsPanel() {
  const [accounts, setAccounts] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await fetch(`${BACKEND_URL}/accounts`).then((r) => r.json());
      setAccounts(data.accounts || []);
    } catch (err) {
      setError(err.message || "Couldn't load accounts.");
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function save() {
    setBusy(true); setError(""); setNote("");
    try {
      const res = await fetch(`${BACKEND_URL}/accounts`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Couldn't save that account.");
      setForm(BLANK);
      setAdding(false);
      setNote(`Saved ${data.service}.`);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally { setBusy(false); }
  }

  async function forget(service) {
    setBusy(true); setError(""); setNote("");
    try {
      const res = await fetch(`${BACKEND_URL}/accounts/${encodeURIComponent(service)}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Couldn't remove it.");
      setNote(`Removed ${service}${data.password_removed ? " and its stored password" : ""}.`);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-5 text-[13px] text-charcoal-300">
      <div>
        <h3 className="text-sm font-medium text-charcoal-100">Accounts in Nova's name</h3>
        <p className="mt-1 leading-relaxed text-charcoal-400">
          Logins you've created for Nova. It knows which sites it has an account on and can sign
          in to them — it can't read the passwords, and it can't create accounts itself.
        </p>
      </div>

      {accounts.length === 0 ? (
        <p className="rounded-md border border-dashed border-charcoal-700 px-3 py-5 text-center text-charcoal-500">
          No accounts yet.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {accounts.map((a) => (
            <li key={a.id} className="rounded-md bg-charcoal-800/50 px-3 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium text-charcoal-100">{a.service}</span>
                <button
                  onClick={() => forget(a.service)}
                  disabled={busy}
                  className="shrink-0 text-[11.5px] text-charcoal-500 transition-colors hover:text-rose-300 disabled:opacity-50"
                >
                  Forget
                </button>
              </div>
              <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11.5px] text-charcoal-500">
                <span>{a.username}</span>
                {a.email && <span>registered to {a.email}</span>}
                {a.url && <span className="truncate">{a.url}</span>}
                <span className={a.has_password ? "text-emerald-400/80" : "text-amber-300/80"}>
                  {a.has_password ? "password stored" : "no password stored"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <div className="space-y-2.5 rounded-md border border-charcoal-700 p-3">
          <div className="grid gap-2.5 sm:grid-cols-2">
            {[["service", "Service", "github"], ["username", "Username or login", "nova"],
              ["url", "Sign-in page", "https://…"], ["email", "Registered to", "nova@…"]].map(
              ([key, label, placeholder]) => (
                <label key={key} className="flex flex-col gap-1 text-[12px] text-charcoal-400">
                  {label}
                  <input
                    value={form[key]}
                    placeholder={placeholder}
                    onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                    className="rounded border border-charcoal-600 bg-charcoal-900 px-2 py-1.5 text-[13px] text-charcoal-100 outline-none focus:border-emerald-500"
                  />
                </label>
              )
            )}
            <label className="flex flex-col gap-1 text-[12px] text-charcoal-400 sm:col-span-2">
              Password
              <input
                type="password"
                value={form.password}
                placeholder="Stored where Nova can use it but never read it"
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="rounded border border-charcoal-600 bg-charcoal-900 px-2 py-1.5 text-[13px] text-charcoal-100 outline-none focus:border-emerald-500"
              />
            </label>
          </div>
          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={busy || !form.service || !form.username}
              className="rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
            >
              Save
            </button>
            <button
              onClick={() => { setAdding(false); setForm(BLANK); setError(""); }}
              className="rounded-md px-3 py-1.5 text-charcoal-400 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="rounded-md px-3 py-1.5 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800"
        >
          Add an account
        </button>
      )}

      {error && <p className="rounded-md bg-rose-500/10 px-3 py-2 leading-relaxed text-rose-300">{error}</p>}
      {note && <p className="rounded-md bg-emerald-500/10 px-3 py-2 text-emerald-300">{note}</p>}

      <p className="border-t border-charcoal-700 pt-3 text-[11.5px] leading-relaxed text-charcoal-500">
        Forgetting an account removes its stored password at the same time, so the vault never
        keeps a secret nobody can identify.
      </p>
    </div>
  );
}
