import { useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "../api.js";
// The pipe-based shell and the basic git view that used to live in this
// file are replaced by these: a real PTY terminal and a git panel with
// history, branches and per-file discard.
import TerminalPanel from "./ide/TerminalPanel.jsx";
import GitPanel from "./ide/GitPanel.jsx";
import ShipPanel from "./ide/ShipPanel.jsx";

async function request(path, options) {
  const res = await fetch(`${BACKEND_URL}/code/${path}`, options);
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}
const post = (path, body) => request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const button = "rounded border border-charcoal-600 px-2 py-1 text-xs text-charcoal-200 hover:border-emerald-400 disabled:opacity-40";
// Secondary actions carry no border. A box says "this is the thing to press";
// a sidebar where every action says that has no hierarchy at all.
const quietAction = "text-[11.5px] text-charcoal-400 transition-colors hover:text-emerald-300 disabled:opacity-40";
const input = "min-w-0 rounded border border-charcoal-600 bg-charcoal-950 px-2 py-1 text-xs text-charcoal-100 outline-none focus:border-emerald-400";

export function ProjectActions({ activePath, onChanged, dirty, createRequest }) {
  const [action, setAction] = useState("");
  const [path, setPath] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const upload = useRef(null);
  useEffect(() => { if (createRequest) { setAction("file"); setPath(""); } }, [createRequest]);
  async function perform(event) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      if (action === "rename" && dirty) throw new Error("Save or close unsaved files before renaming.");
      if (action === "file") await post("file", { path, content: "" });
      else await post(action, { path, new_path: target });
      await onChanged(action === "file" ? path : null, action === "rename");
      setAction(""); setPath(""); setTarget("");
    } catch (caught) { setError(caught.message); }
    finally { setBusy(false); }
  }
  async function importFiles(files) {
    if (!files?.length) return;
    setBusy(true); setError("");
    try {
      const body = new FormData();
      for (const file of files) body.append("files", file);
      const result = await request("import", { method: "POST", body });
      await onChanged(result.paths[0]);
    } catch (caught) { setError(caught.message); }
    finally { setBusy(false); if (upload.current) upload.current.value = ""; }
  }
  return <section className="space-y-2 border-b border-charcoal-700 p-2" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); importFiles(e.dataTransfer.files); }}>
    {/* One quiet row rather than a 2x2 block of bordered buttons. Four boxed
        controls of equal weight was the heaviest thing in a 200px column and
        made none of them look like the usual one. "New file" is gone from
        here on purpose: the file tree below already ends in "+ New file",
        which is the same action sitting where you are already looking. */}
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <button className={quietAction} disabled={busy} onClick={() => { setAction("folder"); setPath(""); }}>New folder</button>
      <button className={quietAction} disabled={busy} onClick={() => upload.current.click()}>Import</button>
      <button className={quietAction} disabled={busy} onClick={() => { setAction("rename"); setPath(activePath || ""); }}>Rename</button>
      <input ref={upload} aria-label="Import project files" type="file" multiple hidden onChange={e => importFiles(e.target.files)} />
    </div>
    {action && <form onSubmit={perform} className="flex flex-col gap-2">
      <label className="text-xs text-charcoal-300">{action === "rename" ? "Existing path" : action === "folder" ? "Folder path" : "File path"}</label>
      <input className={input} aria-label="Project path" autoFocus required value={path} onChange={e => setPath(e.target.value)} placeholder="src/example.py" />
      {action === "rename" && <input className={input} aria-label="New path" required value={target} onChange={e => setTarget(e.target.value)} placeholder="New path" />}
      <div className="flex gap-2"><button className={button} disabled={busy}>{busy ? "Working…" : action === "rename" ? "Rename" : "Create"}</button><button type="button" className={button} onClick={() => setAction("")}>Cancel</button></div>
    </form>}
    {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
  </section>;
}


function Preview() {
  const [address, setAddress] = useState("http://localhost:3000"), [url, setUrl] = useState(""), [error, setError] = useState("");
  const [server, setServer] = useState(null), [pending, setPending] = useState(false);
  useEffect(() => {
    let disposed = false;
    const refresh = () => request('preview').then(data => { if (!disposed) setServer(data); }).catch(() => {});
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => { disposed = true; clearInterval(timer); };
  }, []);
  async function control(action) {
    setPending(true); setError('');
    try {
      const data = await post(`preview/${action}`, {});
      setServer(data);
      if (action === 'start') { setAddress(data.url); setUrl(data.url); }
      else setUrl('');
      if (data.ready === false) setError('Server is still starting. Check logs and reload the preview shortly.');
    } catch (error) { setError(error.message); }
    finally { setPending(false); }
  }
  function open(e) { e.preventDefault(); try { const parsed = new URL(address); if (!["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname) || !["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error("Enter a local development URL, such as http://localhost:3000"); setUrl(parsed.href); setError(""); } catch (caught) { setError(caught.message); } }
  return <section className="flex h-full flex-col gap-2 bg-charcoal-950 p-2"><div className="flex gap-2"><button className={button} disabled={pending || server?.running} onClick={() => control('start')}>{pending ? 'Working…' : 'Start localhost'}</button><button className={button} disabled={pending || !server?.running} onClick={() => control('stop')}>Stop server</button><span className="text-xs text-charcoal-400">{server?.running ? server.root : 'Server stopped'}</span></div><form onSubmit={open} className="flex gap-2"><input aria-label="Local preview URL" className={`${input} flex-1`} value={address} onChange={e => setAddress(e.target.value)} /><button className={button}>Open preview</button>{url && <button type="button" className={button} onClick={() => { setUrl(""); setTimeout(() => setUrl(url), 0); }}>Reload</button>}</form>{error && <p className="text-xs text-rose-300">{error}</p>}{server?.logs?.length > 0 && <details><summary className="text-xs text-charcoal-400">Server logs</summary><pre className="max-h-24 overflow-auto text-xs">{server.logs.join('\n')}</pre></details>}{url ? <iframe key={url} title="Local app preview" src={url} sandbox="allow-scripts allow-forms allow-same-origin" className="min-h-0 flex-1 rounded bg-white" /> : <p className="p-3 text-xs text-charcoal-400">Start localhost for a Next.js or Vite project, or enter an existing local URL.</p>}</section>;
}

export default function IdeTools({ view, workspace }) {
  const [terminalOpened, setTerminalOpened] = useState(false);
  useEffect(() => { if (view === "terminal") setTerminalOpened(true); }, [view]);
  return <>
    {terminalOpened && <div className="h-full" hidden={view !== "terminal"}><TerminalPanel workspace={workspace} active={view === "terminal"} /></div>}
    <div className="h-full" hidden={view !== "git"}><GitPanel key={workspace} workspace={workspace} active={view === "git"} /></div>
    <div className="h-full" hidden={view !== "preview"}><Preview key={workspace} /></div>
    <div className="h-full" hidden={view !== "ship"}><ShipPanel key={workspace} workspace={workspace} active={view === "ship"} /></div>
  </>;
}
