import { useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";

const POLL_MS = 4000;

/** Polls the backend's real /health route (see backend/app/main.py) so the
 * shell can show a genuine connected/disconnected state -- both the top bar's
 * status dot and the Chat reactor's "disconnected" pose (task: "distinct ...
 * disconnected ... states, driven by actual application state") -- instead
 * of assuming the backend is always up. Starts optimistic (connected: true)
 * so the UI doesn't flash disconnected on first paint before the initial
 * check resolves; a real failure still lands within one POLL_MS tick. */
export function useBackendHealth() {
  const [connected, setConnected] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(2500) });
        if (!cancelled) setConnected(res.ok);
      } catch {
        if (!cancelled) setConnected(false);
      }
    }
    check();
    const id = setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return connected;
}
