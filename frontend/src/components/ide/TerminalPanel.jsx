import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { BACKEND_URL } from "../../api.js";

/** A real terminal, backed by a PTY (backend/app/terminal.py).
 *
 * Replaces a pipe-based shell that ran PowerShell with `-NonInteractive`. The
 * difference is not cosmetic: with a pipe there is no tty, so nothing prompts,
 * nothing pages, colours are suppressed, Ctrl-C cannot reach the foreground
 * process, and anything interactive (a Python REPL, `git rebase -i`, an npm
 * prompt, an SSH password) simply hangs. A PTY behaves like a terminal because
 * it is one.
 *
 * The session outlives this component: closing the panel leaves the shell
 * running and reopening replays its scrollback, so a long build is not killed
 * by clicking away.
 */
export default function TerminalPanel({ workspace, active }) {
  const hostRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);
  const socketRef = useRef(null);
  const sessionRef = useRef(null);
  const [status, setStatus] = useState("connecting");
  const [error, setError] = useState("");
  // Bumped by Restart; the setup effect keys on it, so incrementing tears the
  // old session down through the effect's own cleanup and builds a new one.
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let disposed = false;

    const term = new Terminal({
      fontFamily: '"Cascadia Code", "Cascadia Mono", Consolas, monospace',
      fontSize: 12.5,
      cursorBlink: true,
      scrollback: 5000,
      // Matches the app's charcoal/emerald palette rather than xterm's default
      // black, so the panel doesn't read as a foreign window pasted in.
      theme: {
        background: "#0a0b0c", foreground: "#e6ebe8", cursor: "#34d399",
        selectionBackground: "rgba(52,211,153,0.28)",
        black: "#131416", red: "#fb7185", green: "#34d399", yellow: "#fbbf24",
        blue: "#60a5fa", magenta: "#a78bfa", cyan: "#22d3ee", white: "#e6ebe8",
        brightBlack: "#4a4f56", brightRed: "#fda4af", brightGreen: "#6ee7b7",
        brightYellow: "#fcd34d", brightBlue: "#93c5fd", brightMagenta: "#c4b5fd",
        brightCyan: "#67e8f9", brightWhite: "#ffffff",
      },
    });
    // Inside the Paper interface the terminal takes Paper's day or night
    // colors, and follows the switch between them.
    const paper = hostRef.current?.closest(".paper");
    const paperTheme = () => {
      const cs = getComputedStyle(hostRef.current);
      const v = (name) => cs.getPropertyValue(name).trim();
      const night = paper.classList.contains("night");
      return {
        ...term.options.theme,
        background: v("--surf"), foreground: v("--tx"), cursor: v("--tx"), cursorAccent: v("--surf"),
        selectionBackground: night ? "rgba(236,233,228,0.22)" : "rgba(20,20,20,0.14)",
        ...(night ? {} : {
          black: "#141414", red: "#B3261E", green: "#2F7A3F", yellow: "#8A6200", blue: "#2F5EA8",
          magenta: "#7A3FA0", cyan: "#1F6F7A", white: "#5E5A55", brightBlack: "#8F8A83", brightWhite: "#141414",
        }),
      };
    };
    let themeWatch = null;
    if (paper) {
      term.options.theme = paperTheme();
      themeWatch = new MutationObserver(() => { term.options.theme = paperTheme(); });
      themeWatch.observe(paper, { attributes: true, attributeFilter: ["class"] });
    }
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    termRef.current = term;
    fitRef.current = fit;
    try { fit.fit(); } catch { /* host not laid out yet */ }

    (async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/terminal/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cwd: workspace || null, cols: term.cols, rows: term.rows }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not start a terminal");
        if (disposed) {
          fetch(`${BACKEND_URL}/terminal/sessions/${data.id}`, { method: "DELETE" });
          return;
        }
        sessionRef.current = data.id;

        const ws = new WebSocket(`${BACKEND_URL.replace(/^http/, "ws")}/ws/terminal/${data.id}`);
        ws.binaryType = "arraybuffer";
        socketRef.current = ws;
        ws.onopen = () => !disposed && setStatus("ready");
        ws.onmessage = (event) => {
          if (typeof event.data === "string") {
            const message = JSON.parse(event.data);
            if (message.type === "exit") {
              setStatus("exited");
              term.write("\r\n\x1b[38;5;245m[shell exited — Restart to open a new one]\x1b[0m\r\n");
            } else if (message.type === "error") {
              setError(message.message);
            }
            return;
          }
          term.write(new Uint8Array(event.data));
        };
        ws.onclose = () => !disposed && setStatus((s) => (s === "exited" ? s : "closed"));
        ws.onerror = () => !disposed && setError("Terminal connection failed.");

        term.onData((chunk) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(chunk);
        });
        term.onResize(({ cols, rows }) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(`\x00resize:${cols},${rows}`);
        });
      } catch (caught) {
        if (!disposed) setError(caught.message);
      }
    })();

    const observer = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* hidden panel has zero size */ }
    });
    observer.observe(hostRef.current);

    return () => {
      disposed = true;
      observer.disconnect();
      themeWatch?.disconnect();
      socketRef.current?.close();
      term.dispose();
      // The PTY is left running on purpose -- see the component docstring.
    };
  }, [workspace, generation]);

  // The panel is hidden rather than unmounted when another tab is showing, so
  // it has no size while hidden; refit when it comes back or the rows are wrong.
  useEffect(() => {
    if (!active) return;
    const id = setTimeout(() => {
      try { fitRef.current?.fit(); } catch { /* not laid out */ }
      termRef.current?.focus();
    }, 40);
    return () => clearTimeout(id);
  }, [active]);

  async function restart() {
    // Kill the old PTY explicitly: the effect's cleanup deliberately leaves it
    // running (so closing the panel doesn't kill a build), which is exactly
    // what Restart is asking to undo.
    const previous = sessionRef.current;
    if (previous) {
      try {
        await fetch(`${BACKEND_URL}/terminal/sessions/${previous}`, { method: "DELETE" });
      } catch { /* already gone */ }
    }
    termRef.current?.reset();
    setError("");
    setStatus("connecting");
    setGeneration((n) => n + 1);
  }

  return (
    <section className="flex h-full flex-col bg-charcoal-950">
      <div className="flex shrink-0 items-center gap-2 border-b border-charcoal-800 px-2.5 py-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            status === "ready" ? "bg-emerald-400" : status === "connecting" ? "bg-amber-300" : "bg-charcoal-600"
          }`}
          aria-hidden="true"
        />
        <span className="text-[11px] text-charcoal-400">
          {error ? error : status === "ready" ? workspace || "terminal" : status}
        </span>
        <button
          onClick={restart}
          className="ml-auto rounded border border-charcoal-600 px-2 py-0.5 text-[11px] text-charcoal-300 hover:border-emerald-400"
        >
          Restart
        </button>
      </div>
      <div ref={hostRef} className="min-h-0 flex-1 px-1.5 py-1" />
    </section>
  );
}
