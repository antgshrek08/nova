import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../../api.js";

/** Git for the Code tab, backed by backend/app/git_panel.py.
 *
 * Replaces an earlier panel that had status, diff, stage and commit. This adds
 * history, branches, per-file discard, ahead/behind, and rename detection.
 *
 * Deliberately absent: push, force-push, hard reset, branch deletion. Those
 * either lose work or touch a shared remote, and a button is the wrong place
 * for them -- the Terminal tab is right there for the moments you mean it.
 */
async function api(path, options) {
  const response = await fetch(`${BACKEND_URL}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Failed (${response.status})`);
  return data;
}

const btn =
  "rounded border border-charcoal-600 px-2 py-0.5 text-[11px] text-charcoal-300 hover:border-emerald-400 disabled:opacity-40";

export default function GitPanel({ workspace, active }) {
  const [status, setStatus] = useState(null);
  const [tab, setTab] = useState("changes");
  const [commits, setCommits] = useState([]);
  const [branches, setBranches] = useState([]);
  const [diff, setDiff] = useState("");
  const [selected, setSelected] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const query = workspace ? `?path=${encodeURIComponent(workspace)}` : "";

  const refresh = useCallback(async () => {
    try {
      setStatus(await api(`/git/status${query}`));
      setError("");
    } catch (caught) {
      setError(caught.message);
    }
  }, [query]);

  useEffect(() => { if (active) refresh(); }, [active, refresh]);

  useEffect(() => {
    if (!active || !status?.is_repo) return;
    if (tab === "history" && commits.length === 0) {
      api(`/git/log${query}${query ? "&" : "?"}limit=40`).then((d) => setCommits(d.commits)).catch((e) => setError(e.message));
    }
    if (tab === "branches" && branches.length === 0) {
      api(`/git/branches${query}`).then((d) => setBranches(d.branches)).catch((e) => setError(e.message));
    }
  }, [tab, active, status, query, commits.length, branches.length]);

  async function act(action, extra = {}) {
    setBusy(true);
    setError("");
    try {
      setStatus(await api("/git/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, path: workspace || null, ...extra }),
      }));
      if (action === "commit") { setMessage(""); setCommits([]); }
      if (action.endsWith("branch")) { setBranches([]); setCommits([]); }
      setDiff("");
      setSelected(null);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  }

  async function showDiff(file) {
    setSelected(file.path);
    try {
      const staged = Boolean(file.staged) && !file.unstaged;
      const data = await api(
        `/git/diff${query}${query ? "&" : "?"}file=${encodeURIComponent(file.path)}&staged=${staged}`
      );
      setDiff(data.diff || "(no textual diff — binary file, or no changes on this side)");
    } catch (caught) {
      setError(caught.message);
    }
  }

  if (status && !status.is_repo) {
    return (
      <section className="flex h-full items-center justify-center bg-charcoal-950 px-6 text-center">
        <div>
          <p className="text-xs text-charcoal-300">Not a git repository</p>
          <p className="mt-1 text-[11px] text-charcoal-500">{status.root}</p>
          <p className="mt-2 text-[11px] text-charcoal-600">
            Run <code className="text-charcoal-400">git init</code> in the Terminal tab to start one.
          </p>
        </div>
      </section>
    );
  }

  const staged = (status?.files || []).filter((f) => f.staged && !f.untracked);
  const unstaged = (status?.files || []).filter((f) => f.unstaged || f.untracked);

  return (
    <section className="flex h-full gap-3 overflow-hidden bg-charcoal-950 p-2.5 text-xs">
      <div className="flex w-80 shrink-0 flex-col gap-2 overflow-y-auto">
        <div className="flex items-center gap-2">
          <strong className="min-w-0 truncate text-charcoal-200" title={status?.branch}>
            {status?.branch || "Git"}
          </strong>
          {status?.ahead > 0 && <span className="text-[10px] text-emerald-300">↑{status.ahead}</span>}
          {status?.behind > 0 && <span className="text-[10px] text-amber-300">↓{status.behind}</span>}
          <button className={`${btn} ml-auto`} onClick={refresh}>Refresh</button>
        </div>

        <div className="flex gap-1">
          {["changes", "history", "branches"].map((id) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`rounded px-2 py-0.5 text-[11px] capitalize ${
                tab === id ? "bg-charcoal-800 text-emerald-300" : "text-charcoal-500 hover:text-charcoal-300"
              }`}
            >
              {id}
            </button>
          ))}
        </div>

        {error && <p role="alert" className="whitespace-pre-wrap text-[11px] text-rose-300">{error}</p>}

        {tab === "changes" && (
          <>
            {status?.clean && <p className="text-charcoal-500">Working tree is clean.</p>}
            {staged.length > 0 && (
              <FileGroup
                label={`Staged (${staged.length})`}
                files={staged}
                selected={selected}
                onSelect={showDiff}
                busy={busy}
                actions={[["Unstage", (f) => act("unstage", { paths: [f.path] })]]}
              />
            )}
            {unstaged.length > 0 && (
              <FileGroup
                label={`Changes (${unstaged.length})`}
                files={unstaged}
                selected={selected}
                onSelect={showDiff}
                busy={busy}
                actions={[
                  ["Stage", (f) => act("stage", { paths: [f.path] })],
                  ["Discard", (f) => {
                    if (f.untracked) { setError("Untracked files aren't discarded here — delete it in the explorer."); return; }
                    if (window.confirm(`Discard all uncommitted changes to ${f.path}? This cannot be undone.`)) {
                      act("discard", { paths: [f.path] });
                    }
                  }],
                ]}
              />
            )}
            <form
              className="mt-auto flex flex-col gap-1.5 pt-2"
              onSubmit={(e) => { e.preventDefault(); act("commit", { message }); }}
            >
              <textarea
                aria-label="Commit message"
                className="resize-none rounded border border-charcoal-600 bg-charcoal-900 px-2 py-1 text-[11px] text-charcoal-100 outline-none focus:border-emerald-400"
                rows={2}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Commit message"
              />
              <div className="flex gap-1.5">
                <button className={btn} disabled={busy || !message.trim() || staged.length === 0}>
                  Commit {staged.length > 0 ? `(${staged.length})` : ""}
                </button>
                <button
                  type="button"
                  className={btn}
                  disabled={busy || !message.trim() || status?.clean}
                  onClick={() => act("commit", { message, stage_all: true })}
                >
                  Stage all &amp; commit
                </button>
              </div>
            </form>
          </>
        )}

        {tab === "history" && (
          <ul className="space-y-1">
            {commits.map((c) => (
              <li key={c.hash} className="border-b border-charcoal-800/70 pb-1">
                <p className="truncate text-charcoal-200" title={c.subject}>{c.subject}</p>
                <p className="text-[10px] text-charcoal-600">
                  <span className="font-mono text-charcoal-500">{c.short}</span> · {c.author} · {c.when}
                </p>
              </li>
            ))}
            {commits.length === 0 && <li className="text-charcoal-500">No commits yet.</li>}
          </ul>
        )}

        {tab === "branches" && (
          <>
            <ul className="space-y-0.5">
              {branches.map((b) => (
                <li key={b.name} className="flex items-center gap-2">
                  <button
                    disabled={busy || b.current}
                    onClick={() => act("switch_branch", { name: b.name })}
                    className={`min-w-0 flex-1 truncate text-left ${
                      b.current ? "text-emerald-300" : "text-charcoal-300 hover:text-charcoal-100"
                    }`}
                  >
                    {b.current ? "● " : "○ "}{b.name}
                  </button>
                </li>
              ))}
            </ul>
            <form
              className="flex gap-1.5 pt-1"
              onSubmit={(e) => {
                e.preventDefault();
                const name = new FormData(e.currentTarget).get("branch");
                if (name) act("create_branch", { name });
                e.currentTarget.reset();
              }}
            >
              <input
                name="branch"
                aria-label="New branch name"
                className="min-w-0 flex-1 rounded border border-charcoal-600 bg-charcoal-900 px-2 py-0.5 text-[11px] text-charcoal-100 outline-none focus:border-emerald-400"
                placeholder="new-branch"
              />
              <button className={btn} disabled={busy}>Create</button>
            </form>
          </>
        )}
      </div>

      <pre className="min-w-0 flex-1 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-charcoal-400">
        {diff ? colorize(diff) : "Select a changed file to see its diff."}
      </pre>
    </section>
  );
}

function FileGroup({ label, files, selected, onSelect, actions, busy }) {
  return (
    <div>
      <p className="mb-0.5 text-[10px] uppercase tracking-wide text-charcoal-600">{label}</p>
      {files.map((file) => (
        <div key={file.path} className="group flex items-center gap-1 border-b border-charcoal-800/60 py-0.5">
          <span className="w-8 shrink-0 font-mono text-[10px] text-emerald-400/80">
            {(file.staged || file.unstaged || "untracked").slice(0, 3)}
          </span>
          <button
            title={file.renamed_from ? `${file.renamed_from} → ${file.path}` : file.path}
            onClick={() => onSelect(file)}
            className={`min-w-0 flex-1 truncate text-left ${
              selected === file.path ? "text-emerald-300" : "text-charcoal-300 hover:text-charcoal-100"
            }`}
          >
            {file.path}
          </button>
          <span className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            {actions.map(([text, run]) => (
              <button key={text} className={btn} disabled={busy} onClick={() => run(file)}>{text}</button>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Minimal diff colouring. A full parser is not worth it here -- the leading
 * character of each line is the whole grammar that matters for reading one. */
function colorize(text) {
  return text.split("\n").map((line, index) => {
    let className = "text-charcoal-400";
    if (line.startsWith("+") && !line.startsWith("+++")) className = "text-emerald-300";
    else if (line.startsWith("-") && !line.startsWith("---")) className = "text-rose-300";
    else if (line.startsWith("@@")) className = "text-sky-300";
    else if (line.startsWith("diff ") || line.startsWith("index ")) className = "text-charcoal-600";
    return <div key={index} className={className}>{line || " "}</div>;
  });
}
