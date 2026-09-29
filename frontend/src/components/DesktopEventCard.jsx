import { useState } from "react";
import { respondToDesktopAction } from "../api.js";
import { FileIcon } from "./icons.jsx";

// Plain-English verb per tool, so the activity line reads as a sentence
// ("Ran  npm test") rather than an identifier ("run_command"). Anything not
// listed falls back to its own name with underscores spaced out, which reads
// acceptably for the long tail.
const TOOL_VERB = {
  read_file: "Read", write_file: "Wrote", edit_file: "Edited",
  list_dir: "Listed", glob_files: "Found files", grep_files: "Searched",
  move_path: "Moved", delete_path: "Deleted",
  run_command: "Ran", start_process: "Started", stop_process: "Stopped",
  process_output: "Checked output of", run_python: "Ran Python",
  desktop_screenshot: "Took a screenshot", list_windows: "Listed windows",
  focus_window: "Focused", close_window: "Closed", open_app: "Opened",
  list_processes: "Listed processes", kill_process: "Ended process",
  desktop_click: "Clicked", desktop_click_on: "Clicked", desktop_type: "Typed",
  desktop_key: "Pressed", desktop_scroll: "Scrolled",
  browser_act: "Browser", web_search: "Searched the web", web_fetch: "Fetched",
  get_clipboard: "Read the clipboard", set_clipboard: "Copied to clipboard",
  preview_server: "Dev server", list_agents: "Listed agents",
  delegate_to_agent: "Delegated to",
};

// The argument worth showing next to the verb, per tool.
export function toolTarget(name, args = {}) {
  if (!args || typeof args !== "object") return "";
  if (name === "run_command") return String(args.command || "");
  if (name === "run_python") return "script";
  if (name === "web_search") return String(args.query || "");
  if (name === "web_fetch") return String(args.url || "");
  if (name === "browser_act") return `${args.action || ""} ${args.url || args.selector || ""}`.trim();
  if (name === "delegate_to_agent") return String(args.agent || "");
  if (name === "grep_files") return String(args.pattern || "");
  if (name === "glob_files") return String(args.pattern || "");
  if (name === "desktop_key") return String(args.keys || "");
  if (name === "desktop_click_on") return String(args.target || "");
  if (name === "desktop_type") return String(args.text || "").slice(0, 40);
  if (args.path) return String(args.path).split(/[\\/]/).slice(-2).join("/");
  if (args.name) return String(args.name);
  if (args.title_contains) return String(args.title_contains);
  return "";
}

const STATUS_LABEL = {
  pending: "Waiting for your approval…",
  approved: "Approved — running…",
  denied: "Denied",
  timed_out: "Timed out waiting for a response",
  done: "Done",
  error: "Failed",
};

/** Renders one desktop-interaction event inline in a chat message -- either
 * a read-only result (screenshot/window list, already happened, no action
 * needed) or a gated action (click/type/open_app) that's pending, or has
 * been resolved, real per-action approval. See backend/app/desktop_registry.py
 * for the actual gate this UI is a front-end for: nothing the "Allow"
 * button represents has executed before it's clicked. */
export default function DesktopEventCard({ event }) {
  const [responding, setResponding] = useState(false);

  async function respond(approved) {
    setResponding(true);
    try {
      await respondToDesktopAction(event.id, approved);
    } finally {
      setResponding(false);
    }
  }

  if (event.type === "screenshot") {
    return (
      <div className="mt-2 max-w-sm overflow-hidden rounded-lg ring-1 ring-charcoal-700">
        {event.error ? (
          <p className="p-2 text-xs text-rose-400">⚠️ Screenshot failed: {event.error}</p>
        ) : (
          <img
            src={`data:image/png;base64,${event.imageBase64}`}
            alt="Screenshot N.O.V.A. just captured"
            className="w-full"
          />
        )}
      </div>
    );
  }

  if (event.type === "list_windows") {
    return (
      <div className="mt-2 max-w-sm rounded-lg bg-charcoal-800/60 p-2 text-xs">
        {event.error ? (
          <p className="text-rose-400">⚠️ Couldn't list windows: {event.error}</p>
        ) : (
          <ul className="space-y-0.5">
            {event.windows.map((w, i) => (
              <li key={i} className={`truncate ${w.active ? "text-emerald-300" : "text-charcoal-300"}`}>
                {w.active && "▸ "}
                {w.title}
                {w.process && <span className="text-charcoal-500"> — {w.process}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  // One tool the agent loop called this turn (backend/app/agent_loop.py).
  // Deliberately a single compact line rather than a card: a turn routinely
  // runs six or eight of these, and eight cards would bury the actual answer.
  if (event.type === "tool") {
    const verb = TOOL_VERB[event.name] || event.name.replace(/_/g, " ");
    const running = event.status === "running";
    const failed = event.status === "error";
    return (
      <div className="mt-1.5 flex max-w-lg items-center gap-2 text-[11px]">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            failed ? "bg-rose-400" : running ? "bg-amber-300 animate-pulse motion-reduce:animate-none" : "bg-emerald-500/70"
          }`}
          aria-hidden="true"
        />
        <span className={failed ? "text-rose-300" : "text-charcoal-400"}>{verb}</span>
        {event.target && (
          <span className="min-w-0 truncate font-mono text-charcoal-300" title={event.target}>
            {event.target}
          </span>
        )}
        {event.summary && !failed && <span className="shrink-0 text-charcoal-600">· {event.summary}</span>}
        {failed && event.summary && (
          <span className="min-w-0 truncate text-rose-400/80" title={event.summary}>
            · {event.summary}
          </span>
        )}
      </div>
    );
  }

  // A provider went down mid-turn and the loop moved to the next one. Shown
  // because the model badge changes underneath the user; silently swapping
  // models would be the more confusing choice.
  if (event.type === "reroute") {
    return (
      <div className="mt-1.5 flex max-w-lg items-center gap-2 text-[11px] text-charcoal-500">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-charcoal-600" aria-hidden="true" />
        <span>
          {event.from} was unavailable — switched to another model
        </span>
      </div>
    );
  }

  if (event.type === "file") {
    const verb = { read: "Read", find: "Searched names for", search: "Searched contents for", list: "Listed" }[event.kind] || event.kind;
    const name = event.kind === "read" || event.kind === "list"
      ? String(event.detail || "").split(/[\\/]/).pop()
      : event.detail;
    return (
      <div className="mt-2 flex max-w-sm flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-lg bg-charcoal-800/60 px-2.5 py-1.5 text-[11px]">
        <FileIcon className="h-3 w-3 shrink-0 text-charcoal-500" />
        {event.error ? (
          <span className="text-rose-400">Couldn&apos;t {verb.toLowerCase()} {name}: {event.error}</span>
        ) : (
          <>
            <span className="text-charcoal-400">{verb}</span>
            <span className="min-w-0 truncate font-mono text-charcoal-200" title={event.detail}>{name}</span>
            {event.kind === "read" && event.bytes != null && (
              <span className="text-charcoal-500">· {event.bytes.toLocaleString()} bytes{event.truncated ? ", truncated" : ""}</span>
            )}
            {event.kind !== "read" && event.count != null && (
              <span className="text-charcoal-500">
                · {event.count} {event.kind === "list"
                  ? `entr${event.count === 1 ? "y" : "ies"}`
                  : `match${event.count === 1 ? "" : "es"}`}
              </span>
            )}
            {event.withheld > 0 && (
              <span className="text-amber-300/90" title="Credential files are never read">· {event.withheld} withheld</span>
            )}
          </>
        )}
      </div>
    );
  }

  // Gated action -- pending or resolved.
  const status = event.status || "pending";
  const isPending = status === "pending";
  return (
    <div className="mt-2 max-w-sm rounded-lg border border-amber-700/50 bg-amber-950/20 p-2.5 text-xs">
      <p className="mb-1.5 font-medium text-amber-200">
        N.O.V.A. wants to: <span className="font-mono text-charcoal-100">{event.description}</span>
      </p>
      {isPending ? (
        <div className="flex gap-2">
          <button
            onClick={() => respond(true)}
            disabled={responding}
            className="rounded-md bg-emerald-600 px-2.5 py-1 font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            Allow
          </button>
          <button
            onClick={() => respond(false)}
            disabled={responding}
            className="rounded-md px-2.5 py-1 font-medium text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
          >
            Deny
          </button>
        </div>
      ) : (
        <p
          className={
            status === "done"
              ? "text-emerald-400"
              : status === "error"
                ? "text-rose-400"
                : "text-charcoal-400"
          }
        >
          {STATUS_LABEL[status] || status}
          {event.error && `: ${event.error}`}
        </p>
      )}
    </div>
  );
}
