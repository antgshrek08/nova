// How many models the user has ready, which decides whether Workspace is
// unlocked (a team needs at least four: planning, research, doing, checking).
import { useCallback, useEffect, useState } from "react";
import { listCustomModels, listModels } from "../api.js";

export const WORKSPACE_MIN_MODELS = 4;

export async function readyModels() {
  const [builtIn, custom] = await Promise.all([
    listModels().catch(() => []),
    listCustomModels().catch(() => []),
  ]);
  const byId = new Map();
  (Array.isArray(builtIn) ? builtIn : []).forEach((m) => { if (m.enabled) byId.set(m.id, m); });
  (Array.isArray(custom) ? custom : custom?.models || []).forEach((m) => {
    if (m.enabled) byId.set(`custom:${m.id}`, { id: `custom:${m.id}`, name: m.name, provider: m.provider });
  });
  return [...byId.values()];
}

export function useModelCount() {
  const [count, setCount] = useState(null);
  const refresh = useCallback(() => { readyModels().then((m) => setCount(m.length)).catch(() => setCount(0)); }, []);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);
  return { count, unlocked: count != null && count >= WORKSPACE_MIN_MODELS, refresh };
}
