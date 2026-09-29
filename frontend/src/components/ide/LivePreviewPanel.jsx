import React, { useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "../../api.js";

async function request(path, options) {
  const res = await fetch(`${BACKEND_URL}/code/${path}`, options);
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

const post = (path, body) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export default function LivePreviewPanel({ onClose }) {
  const [address, setAddress] = useState("http://localhost:3000");
  const [url, setUrl] = useState("http://localhost:3000");
  const [error, setError] = useState("");
  const [server, setServer] = useState(null);
  const [pending, setPending] = useState(false);
  const [viewport, setViewport] = useState("responsive"); // 'responsive' | 'tablet' | 'mobile'
  const [showLogs, setShowLogs] = useState(false);
  const iframeRef = useRef(null);

  // Poll server state every 3s
  useEffect(() => {
    let disposed = false;
    const refresh = () =>
      request("preview")
        .then((data) => {
          if (!disposed) {
            setServer(data);
            if (data.running && data.url && !url) {
              setUrl(data.url);
              setAddress(data.url);
            }
          }
        })
        .catch(() => {});
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [url]);

  async function handleControl(action) {
    setPending(true);
    setError("");
    try {
      const data = await post(`preview/${action}`, {});
      setServer(data);
      if (action === "start") {
        const targetUrl = data.url || "http://localhost:3000";
        setAddress(targetUrl);
        setUrl(targetUrl);
      } else {
        setUrl("");
      }
      if (data.ready === false) {
        setError("Dev server is compiling… check logs or reload shortly.");
      }
    } catch (err) {
      setError(err.message || `Failed to ${action} server`);
    } finally {
      setPending(false);
    }
  }

  function handleNavigate(e) {
    if (e) e.preventDefault();
    try {
      const parsed = new URL(address);
      if (!["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname)) {
        throw new Error("Only local development addresses (localhost/127.0.0.1) are permitted.");
      }
      setUrl(parsed.href);
      setError("");
    } catch (caught) {
      setError(caught.message);
    }
  }

  function handleReload() {
    if (iframeRef.current) {
      const current = url;
      setUrl("");
      setTimeout(() => setUrl(current), 100);
    }
  }

  const isRunning = Boolean(server?.running);

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col border-l border-charcoal-700 bg-charcoal-950">
      {/* Top Address & Control Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-charcoal-800 bg-charcoal-900/90 px-3 py-2">
        <div className="flex items-center gap-2">
          {/* Server status pill */}
          <div className="flex items-center gap-1.5 rounded-full bg-charcoal-800 px-2 py-0.5 text-[11px] font-medium text-charcoal-300">
            <span
              className={`h-2 w-2 rounded-full ${
                isRunning ? "bg-emerald-400 animate-pulse shadow-sm shadow-emerald-400/50" : "bg-charcoal-500"
              }`}
            />
            <span>{isRunning ? "Live" : "Offline"}</span>
          </div>

          <button
            onClick={() => handleControl(isRunning ? "stop" : "start")}
            disabled={pending}
            className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors disabled:opacity-50 ${
              isRunning
                ? "bg-charcoal-800 text-rose-300 hover:bg-rose-500/20"
                : "bg-emerald-600 text-white hover:bg-emerald-500 shadow-sm"
            }`}
          >
            {pending ? "Working…" : isRunning ? "Stop" : "Run Dev Server"}
          </button>
        </div>

        {/* Viewport switch: Desktop, Tablet, Mobile */}
        <div className="flex items-center rounded-lg border border-charcoal-800 bg-charcoal-950 p-0.5 text-xs text-charcoal-400">
          <button
            onClick={() => setViewport("responsive")}
            title="Desktop / Responsive Width"
            className={`rounded px-2 py-0.5 transition-colors ${
              viewport === "responsive" ? "bg-charcoal-800 text-emerald-400 font-medium" : "hover:text-charcoal-200"
            }`}
          >
            Desktop
          </button>
          <button
            onClick={() => setViewport("tablet")}
            title="Tablet Width (768px)"
            className={`rounded px-2 py-0.5 transition-colors ${
              viewport === "tablet" ? "bg-charcoal-800 text-emerald-400 font-medium" : "hover:text-charcoal-200"
            }`}
          >
            768px
          </button>
          <button
            onClick={() => setViewport("mobile")}
            title="Mobile Width (375px)"
            className={`rounded px-2 py-0.5 transition-colors ${
              viewport === "mobile" ? "bg-charcoal-800 text-emerald-400 font-medium" : "hover:text-charcoal-200"
            }`}
          >
            375px
          </button>
        </div>

        {/* Close split preview */}
        {onClose && (
          <button
            onClick={onClose}
            title="Close Live Preview panel"
            className="rounded p-1 text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
          >
            ✕
          </button>
        )}
      </div>

      {/* URL Input Bar */}
      <form onSubmit={handleNavigate} className="flex shrink-0 items-center gap-2 border-b border-charcoal-800/80 bg-charcoal-900/40 px-3 py-1.5">
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="http://localhost:3000"
          className="flex-1 rounded-md border border-charcoal-700 bg-charcoal-950 px-2.5 py-1 text-xs text-charcoal-100 font-mono outline-none focus:border-emerald-500"
        />
        <button
          type="submit"
          className="rounded-md border border-charcoal-700 bg-charcoal-800 px-2 py-1 text-xs font-medium text-charcoal-200 hover:border-emerald-500 hover:text-white"
        >
          Go
        </button>
        <button
          type="button"
          onClick={handleReload}
          title="Reload Preview"
          className="rounded-md border border-charcoal-700 bg-charcoal-800 px-2 py-1 text-xs font-medium text-charcoal-200 hover:bg-charcoal-700"
        >
          ↻
        </button>
        <button
          type="button"
          onClick={() => setShowLogs((prev) => !prev)}
          className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
            showLogs ? "bg-charcoal-700 text-emerald-400" : "text-charcoal-400 hover:bg-charcoal-800"
          }`}
        >
          Logs
        </button>
      </form>

      {error && (
        <div className="shrink-0 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300 border-b border-rose-500/20">
          {error}
        </div>
      )}

      {/* Main Preview Area */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto bg-charcoal-950/80 p-3">
        {url ? (
          <div
            className={`h-full transition-all duration-200 ${
              viewport === "mobile"
                ? "w-[375px] max-w-full rounded-2xl border-4 border-charcoal-800 shadow-2xl overflow-hidden"
                : viewport === "tablet"
                ? "w-[768px] max-w-full rounded-xl border-2 border-charcoal-800 shadow-xl overflow-hidden"
                : "w-full rounded-lg shadow-sm"
            }`}
          >
            <iframe
              ref={iframeRef}
              title="Studio Live Preview"
              src={url}
              sandbox="allow-scripts allow-forms allow-same-origin allow-modals"
              className="h-full w-full bg-white border-0"
            />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center p-6 text-center text-xs text-charcoal-500">
            <span className="text-2xl mb-2">⚡</span>
            <p className="font-medium text-charcoal-400">Dev server stopped</p>
            <p className="mt-1 max-w-xs text-charcoal-500">
              Click &quot;Run Dev Server&quot; above to launch Next.js or Vite automatically, or enter an active local port.
            </p>
          </div>
        )}
      </div>

      {/* Collapsible Server Logs */}
      {showLogs && (
        <div className="shrink-0 border-t border-charcoal-800 bg-charcoal-900 p-2">
          <div className="flex items-center justify-between pb-1 text-[11px] font-semibold text-charcoal-400">
            <span>Server Console Logs</span>
            <button onClick={() => setShowLogs(false)} className="hover:text-charcoal-200">
              Hide
            </button>
          </div>
          <pre className="max-h-28 overflow-auto font-mono text-[10px] text-charcoal-300 whitespace-pre-wrap select-text">
            {server?.logs?.length ? server.logs.join("\n") : "No logs recorded yet."}
          </pre>
        </div>
      )}
    </div>
  );
}
