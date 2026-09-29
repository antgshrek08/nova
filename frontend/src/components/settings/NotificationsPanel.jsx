import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../../api.js";
import * as push from "../../lib/push.js";

/** Turning on the one channel that runs the other way.
 *
 * Most of this component is not the toggle. It is the explanation, because
 * the toggle fails for four different reasons and only one of them is
 * "something is broken". On an iPhone the usual answer is that Nova is open
 * in Safari rather than from the Home Screen icon, and a user told only
 * "couldn't enable notifications" will reasonably conclude the feature does
 * not work and never try again.
 */
export default function NotificationsPanel() {
  const [devices, setDevices] = useState([]);
  const [subscribed, setSubscribed] = useState(false);
  const [blocked, setBlocked] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState(null);

  const refresh = useCallback(async () => {
    setBlocked(push.blocker());
    try {
      setSubscribed(Boolean(await push.currentSubscription()));
    } catch {
      setSubscribed(false);
    }
    try {
      setDevices(await fetch(`${BACKEND_URL}/push/devices`).then((r) => r.json()));
    } catch {
      setDevices([]);
    }
    try {
      setPreview(await fetch(`${BACKEND_URL}/push/reminder/preview`).then((r) => r.json()));
    } catch {
      setPreview(null);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function turnOn() {
    setBusy(true); setError(""); setNote("");
    try {
      await push.enable();
      setNote("This device is registered. Send a test to confirm it arrives.");
      await refresh();
    } catch (err) {
      setError(err.message || "Couldn't turn on notifications.");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true); setError(""); setNote("");
    try {
      await push.disable();
      setNote("This device will no longer be notified.");
      await refresh();
    } catch (err) {
      setError(err.message || "Couldn't turn notifications off.");
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    setBusy(true); setError(""); setNote("");
    try {
      const result = await fetch(`${BACKEND_URL}/push/test`, { method: "POST" }).then((r) => r.json());
      setNote(
        result.sent
          ? `Sent to ${result.sent} device${result.sent === 1 ? "" : "s"}. It should appear in a second or two.`
          : `Nothing was sent — ${result.reason || "no device accepted it"}.`
      );
      await refresh();
    } catch (err) {
      setError(err.message || "Couldn't send the test.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5 text-[13px] text-charcoal-300">
      <div>
        <h3 className="text-sm font-medium text-charcoal-100">Let Nova reach you</h3>
        <p className="mt-1 leading-relaxed text-charcoal-400">
          Everything else in Nova waits to be asked. This is the one channel that runs the other
          way — Nova notices something and tells you, whether or not the app is open.
        </p>
      </div>

      {blocked ? (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 leading-relaxed text-amber-200">
          {blocked}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {subscribed ? (
            <button
              onClick={turnOff}
              disabled={busy}
              className="rounded-md px-3 py-1.5 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 disabled:opacity-50"
            >
              Turn off on this device
            </button>
          ) : (
            <button
              onClick={turnOn}
              disabled={busy}
              className="rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
            >
              {busy ? "Working…" : "Turn on for this device"}
            </button>
          )}
          <button
            onClick={sendTest}
            disabled={busy || devices.length === 0}
            className="rounded-md px-3 py-1.5 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 disabled:opacity-50"
          >
            Send a test
          </button>
        </div>
      )}

      {error && <p className="rounded-md bg-rose-500/10 px-3 py-2 text-rose-300">{error}</p>}
      {note && <p className="rounded-md bg-emerald-500/10 px-3 py-2 text-emerald-300">{note}</p>}

      <div>
        <h4 className="mb-1.5 text-[12.5px] font-medium text-charcoal-200">
          Devices {devices.length > 0 && <span className="text-charcoal-500">({devices.length})</span>}
        </h4>
        {devices.length === 0 ? (
          <p className="text-charcoal-500">No devices yet.</p>
        ) : (
          <ul className="space-y-1">
            {devices.map((d) => (
              <li key={d.id} className="flex items-baseline justify-between gap-3 rounded-md bg-charcoal-800/50 px-2.5 py-1.5">
                <span className="text-charcoal-200">{d.label}</span>
                <span className="shrink-0 text-[11px] text-charcoal-500">
                  {d.last_sent_at ? `last notified ${d.last_sent_at}` : `added ${d.created_at}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="mb-1.5 text-[12.5px] font-medium text-charcoal-200">What Nova will send</h4>
        <p className="leading-relaxed text-charcoal-400">
          One message a day, at 6pm, listing what's due tomorrow — and nothing at all on a day
          with nothing due. A nightly "all clear" is how a reminder turns into something you
          switch off.
        </p>
        {preview && (
          <p className="mt-2 rounded-md bg-charcoal-800/50 px-3 py-2">
            {preview.would_send ? (
              <>
                <span className="font-medium text-charcoal-100">{preview.title}</span>
                <span className="block text-charcoal-400">{preview.body}</span>
              </>
            ) : (
              <span className="text-charcoal-500">Tonight: nothing would be sent — {preview.reason}.</span>
            )}
          </p>
        )}
      </div>

      {push.isIOS() && (
        <p className="border-t border-charcoal-700 pt-3 text-[12px] leading-relaxed text-charcoal-500">
          On iPhone, notifications only work when Nova is opened from a Home Screen icon. In
          Safari, tap Share, then "Add to Home Screen", then open Nova from that icon and come
          back here. This is an iOS rule, not a Nova one.
        </p>
      )}
    </div>
  );
}
