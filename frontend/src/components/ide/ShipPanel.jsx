import { useCallback, useEffect, useState } from "react";
import {
  getShipStatus,
  runShipBuild,
  pushShipGit,
  deployShipProvider,
  getCustomConnectors,
  saveCustomConnector,
} from "../../api.js";

/** ShipPanel: Free Zero-API Deployments, GitHub Push & Extensibility Hub */
const POLL_MS = 1500;

export default function ShipPanel({ workspace, active }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [pushResult, setPushResult] = useState(null);
  const [deploying, setDeploying] = useState(null); // 'vercel' | 'netlify' | etc.
  const [deployResult, setDeployResult] = useState(null);
  const [connectors, setConnectors] = useState([]);
  const [showConnectors, setShowConnectors] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await getShipStatus(workspace);
      setState(s);
      setError("");
    } catch (err) {
      setError(err.message || "Could not read project state.");
    }
  }, [workspace]);

  const loadConnectors = useCallback(async () => {
    try {
      const list = await getCustomConnectors();
      setConnectors(list || []);
    } catch (e) {
      console.warn("Could not load connectors:", e);
    }
  }, []);

  useEffect(() => {
    if (active) {
      load();
      loadConnectors();
    }
  }, [active, load, loadConnectors]);

  useEffect(() => {
    if (!active || !state?.build?.running) return undefined;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [active, state?.build?.running, load]);

  async function handleBuild() {
    setStarting(true);
    try {
      const result = await runShipBuild(workspace);
      if (!result.started) setError(result.reason || "Could not start the build.");
      await load();
    } catch (err) {
      setError(err.message || "Could not start the build.");
    } finally {
      setStarting(false);
    }
  }

  async function handlePush() {
    setPushing(true);
    setPushResult(null);
    try {
      const res = await pushShipGit(workspace, "origin", state?.git?.branch || "main");
      setPushResult(res);
      await load();
    } catch (err) {
      setPushResult({ ok: false, message: err.message || "Push failed." });
    } finally {
      setPushing(false);
    }
  }

  async function handleDeploy(target) {
    setDeploying(target);
    setDeployResult(null);
    try {
      const res = await deployShipProvider(workspace, target);
      setDeployResult(res);
      await load();
    } catch (err) {
      setDeployResult({ ok: false, message: err.message || `Deploy to ${target} failed.` });
    } finally {
      setDeploying(null);
    }
  }

  if (!state) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-charcoal-500">
        {error || "Reading project…"}
      </div>
    );
  }

  const { project, git, blockers, ready } = state;
  const buildState = state.build || {};

  return (
    <div className="h-full overflow-y-auto bg-charcoal-950 p-4 font-sans text-charcoal-200">
      <div className="mx-auto max-w-3xl space-y-4">
        {/* Top Status Banner */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-charcoal-800 bg-charcoal-900/70 p-3">
          <div className="flex items-center gap-2.5">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide uppercase ${
                ready ? "bg-emerald-500/20 text-emerald-300" : "bg-charcoal-800 text-charcoal-400"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${ready ? "bg-emerald-400 animate-pulse" : "bg-charcoal-500"}`} />
              {ready ? "Ready to ship" : "Pre-flight checks"}
            </span>
            <span className="font-mono text-xs font-medium text-white">{project.name}</span>
            {project.framework && (
              <span className="rounded bg-sky-950/60 border border-sky-800/40 px-2 py-0.5 text-[10.5px] text-sky-300">
                {project.framework}
              </span>
            )}
            {project.markers.map((m) => (
              <span key={m} className="rounded bg-charcoal-800 px-2 py-0.5 text-[10.5px] text-charcoal-400">
                {m}
              </span>
            ))}
          </div>

          <button
            onClick={() => setShowConnectors(!showConnectors)}
            className="flex items-center gap-1.5 rounded-md border border-charcoal-700 bg-charcoal-800/80 px-2.5 py-1 text-[11px] text-charcoal-300 hover:border-charcoal-600 hover:text-white"
          >
            <span>🔌 Connectors & Modder</span>
            <span className="rounded bg-charcoal-700 px-1.5 py-0.2 text-[10px] text-charcoal-300">
              {connectors.length}
            </span>
          </button>
        </div>

        {error && <p className="rounded-md bg-rose-500/10 p-2 text-xs text-rose-300">{error}</p>}

        {/* Git & GitHub Zero-API Row */}
        <div className="rounded-lg border border-charcoal-800 bg-charcoal-900/40 p-3.5 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-charcoal-400 uppercase tracking-wider">Source Control</span>
              {git.is_repo && <code className="rounded bg-charcoal-800 px-2 py-0.5 text-xs text-sky-400 font-mono">{git.branch}</code>}
            </div>
            {git.is_repo && (
              <button
                onClick={handlePush}
                disabled={pushing || !git.remote}
                className="flex items-center gap-1.5 rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white shadow hover:bg-indigo-500 disabled:opacity-50"
              >
                <span>{pushing ? "Pushing…" : "🚀 1-Click Push to GitHub"}</span>
              </button>
            )}
          </div>

          {git.is_repo ? (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-charcoal-400">Remote:</span>
              {git.remote ? (
                <span className="truncate max-w-md font-mono text-emerald-400/90">{git.remote}</span>
              ) : (
                <Flag tone="amber">No remote configured</Flag>
              )}
              {git.uncommitted > 0 ? (
                <Flag tone="amber">{git.uncommitted} uncommitted changes</Flag>
              ) : (
                <Flag tone="good">Working tree clean</Flag>
              )}
              {git.ahead > 0 && <Flag tone="amber">{git.ahead} commits unpushed</Flag>}
            </div>
          ) : (
            <p className="text-xs text-charcoal-400">This folder is not a Git repository yet. Initialize one in the Git tab or terminal.</p>
          )}

          {pushResult && (
            <div className={`rounded p-2 text-xs font-mono whitespace-pre-wrap ${pushResult.ok ? "bg-emerald-950/40 text-emerald-300 border border-emerald-800/40" : "bg-rose-950/40 text-rose-300 border border-rose-800/40"}`}>
              {pushResult.message}
            </div>
          )}
        </div>

        {/* Free Zero-API Deploy Targets */}
        <div className="rounded-lg border border-charcoal-800 bg-charcoal-900/40 p-3.5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-charcoal-400 uppercase tracking-wider">Free Zero-API Deployments</span>
            <span className="text-[11px] text-emerald-400/90 bg-emerald-950/40 border border-emerald-800/30 px-2 py-0.5 rounded">
              ✓ No API keys required
            </span>
          </div>
          <p className="text-xs text-charcoal-400">
            Nova connects to free deployment tools directly via native CLI & Git workflows. No paid cloud tokens or third-party API fees required.
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
            <button
              onClick={() => handleDeploy("vercel")}
              disabled={deploying !== null}
              className="flex flex-col items-center justify-center p-2.5 rounded-lg border border-charcoal-800 bg-charcoal-900 hover:border-charcoal-700 hover:bg-charcoal-800/80 transition-all text-center group disabled:opacity-40"
            >
              <span className="text-sm font-semibold text-white group-hover:text-emerald-400">▲ Vercel</span>
              <span className="text-[10.5px] text-charcoal-500 mt-0.5">Free CLI Deploy</span>
            </button>

            <button
              onClick={() => handleDeploy("netlify")}
              disabled={deploying !== null}
              className="flex flex-col items-center justify-center p-2.5 rounded-lg border border-charcoal-800 bg-charcoal-900 hover:border-charcoal-700 hover:bg-charcoal-800/80 transition-all text-center group disabled:opacity-40"
            >
              <span className="text-sm font-semibold text-white group-hover:text-teal-400">◈ Netlify</span>
              <span className="text-[10.5px] text-charcoal-500 mt-0.5">Free Static / Edge</span>
            </button>

            <button
              onClick={() => handleDeploy("replit")}
              disabled={deploying !== null}
              className="flex flex-col items-center justify-center p-2.5 rounded-lg border border-charcoal-800 bg-charcoal-900 hover:border-charcoal-700 hover:bg-charcoal-800/80 transition-all text-center group disabled:opacity-40"
            >
              <span className="text-sm font-semibold text-white group-hover:text-amber-400">⚡ Replit</span>
              <span className="text-[10.5px] text-charcoal-500 mt-0.5">Cloud Mirror</span>
            </button>

            <button
              onClick={() => handleDeploy("lovable")}
              disabled={deploying !== null}
              className="flex flex-col items-center justify-center p-2.5 rounded-lg border border-charcoal-800 bg-charcoal-900 hover:border-charcoal-700 hover:bg-charcoal-800/80 transition-all text-center group disabled:opacity-40"
            >
              <span className="text-sm font-semibold text-white group-hover:text-rose-400">♥ Lovable UI</span>
              <span className="text-[10.5px] text-charcoal-500 mt-0.5">Component Sync</span>
            </button>
          </div>

          {deploying && (
            <div className="flex items-center gap-2 rounded bg-charcoal-900 border border-charcoal-700 p-2 text-xs text-charcoal-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
              <span>Executing zero-API deployment for {deploying}…</span>
            </div>
          )}

          {deployResult && (
            <div className={`rounded p-2.5 text-xs font-mono whitespace-pre-wrap ${deployResult.ok ? "bg-emerald-950/40 text-emerald-300 border border-emerald-800/40" : "bg-rose-950/40 text-rose-300 border border-rose-800/40"}`}>
              <div className="font-semibold mb-1">{deployResult.message}</div>
              {deployResult.output && <div className="text-[11px] text-charcoal-300 max-h-36 overflow-auto">{deployResult.output}</div>}
            </div>
          )}
        </div>

        {/* Local Verification Build */}
        <div className="rounded-lg border border-charcoal-800 bg-charcoal-900/40 p-3.5 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-charcoal-400 uppercase tracking-wider">Local Build Engine</span>
              {buildState.command && <code className="text-[11px] text-charcoal-400 font-mono">{buildState.command}</code>}
            </div>
            <div className="flex items-center gap-2">
              {buildState.ok === true && !buildState.running && <Flag tone="good">✓ Passed</Flag>}
              {buildState.ok === false && !buildState.running && <Flag tone="bad">✗ Failed</Flag>}
              <button
                onClick={handleBuild}
                disabled={starting || buildState.running || !project.build_command}
                className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
              >
                {buildState.running ? "Building…" : starting ? "Starting…" : "Run Build"}
              </button>
            </div>
          </div>

          {buildState.output?.length > 0 ? (
            <pre className="max-h-52 overflow-auto rounded bg-charcoal-950 p-2.5 text-[11px] font-mono leading-relaxed text-charcoal-300 border border-charcoal-800">
              {buildState.output.join("\n")}
            </pre>
          ) : (
            <p className="text-xs text-charcoal-500">
              Test your project locally before publishing to catch compile issues instantly.
            </p>
          )}
        </div>

        {/* Modder & Connectors Drawer */}
        {showConnectors && (
          <div className="rounded-lg border border-indigo-900/50 bg-indigo-950/20 p-3.5 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-indigo-300 uppercase tracking-wider">
                Nova Open Architecture (Custom Tabs & Connectors)
              </span>
              <span className="text-[11px] text-indigo-400">100% Extensible</span>
            </div>
            <p className="text-xs text-charcoal-300">
              Need another tab or connector? Ask Nova in Chat or Studio to design and register it. Nova can generate widgets, flashcards, 3D math tools, or new school connectors on the fly!
            </p>

            <div className="space-y-2">
              {connectors.map((c) => (
                <div key={c.id} className="flex items-center justify-between rounded bg-charcoal-900/80 border border-charcoal-800 px-3 py-2 text-xs">
                  <div>
                    <span className="font-medium text-white">{c.name}</span>
                    <span className="ml-2 rounded bg-charcoal-800 px-1.5 py-0.5 text-[10px] text-charcoal-400">{c.auth_type}</span>
                    <p className="text-[11px] text-charcoal-400 mt-0.5">{c.description}</p>
                  </div>
                  <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                    Active
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Flag({ tone, children }) {
  const tones = {
    good: "bg-emerald-600/20 text-emerald-300 border border-emerald-800/30",
    amber: "bg-amber-500/15 text-amber-300 border border-amber-800/30",
    bad: "bg-rose-500/15 text-rose-300 border border-rose-800/30",
    quiet: "bg-charcoal-800 text-charcoal-400",
  };
  return <span className={`rounded-full px-2.5 py-0.5 text-[10.5px] font-medium ${tones[tone]}`}>{children}</span>;
}
