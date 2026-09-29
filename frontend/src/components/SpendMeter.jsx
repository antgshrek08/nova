import { useEffect, useState } from "react";
import { getSpend } from "../api.js";

const POLL_MS = 4000;

export default function SpendMeter({ refreshKey }) {
  const [spend, setSpend] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getSpend();
        if (!cancelled) setSpend(data);
      } catch {
        // Backend not reachable yet; keep showing the last-known value.
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshKey]);

  if (!spend) return null;

  const over = spend.over_budget;

  return (
    <div
      className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium ${
        over ? "bg-red-950 text-red-300" : "bg-slate-800 text-slate-300"
      }`}
      title={`${spend.call_count} call(s), ${spend.total_tokens} tokens today (${spend.date})`}
    >
      <span className={`h-2 w-2 rounded-full ${over ? "bg-red-500" : "bg-slate-500"}`} />
      <span>
        ${spend.total_cost_usd.toFixed(4)} / ${spend.daily_budget_usd.toFixed(2)} today
      </span>
    </div>
  );
}
