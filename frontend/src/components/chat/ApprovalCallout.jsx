import { useState } from "react";
import { respondToDesktopAction } from "../../api.js";

/** Compact "needs your attention now" surface for a pending desktop_confirm
 * action, shown in the central Chat stage next to the reactor (design intent:
 * "show the actual approval request and its controls clearly") -- separate
 * from DesktopEventCard's inline copy of the same event in the transcript,
 * which stays as the permanent record. Both read the same event/status, so
 * clicking Allow/Deny here resolves it everywhere at once (same
 * respondToDesktopAction call DesktopEventCard uses); this callout just
 * stops rendering once the event's status is no longer "pending", the
 * instant the real desktop_result arrives on the stream. */
export default function ApprovalCallout({ event }) {
  const [responding, setResponding] = useState(false);

  async function respond(approved) {
    setResponding(true);
    try {
      await respondToDesktopAction(event.id, approved);
    } finally {
      setResponding(false);
    }
  }

  return (
    <div className="w-full max-w-sm rounded-xl border border-amber-500/40 bg-amber-950/25 p-3.5 text-sm shadow-[0_0_30px_rgba(251,191,36,0.08)]">
      <p className="mb-2.5 leading-snug text-amber-100">
        N.O.V.A. wants to: <span className="font-medium text-white">{event.description}</span>
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => respond(true)}
          disabled={responding}
          className="rounded-lg bg-amber-500 px-3.5 py-1.5 text-sm font-medium text-charcoal-950 hover:bg-amber-400 disabled:opacity-50"
        >
          Allow
        </button>
        <button
          onClick={() => respond(false)}
          disabled={responding}
          className="rounded-lg px-3.5 py-1.5 text-sm font-medium text-amber-200 ring-1 ring-amber-500/40 hover:bg-amber-500/10 disabled:opacity-50"
        >
          Deny
        </button>
      </div>
    </div>
  );
}
