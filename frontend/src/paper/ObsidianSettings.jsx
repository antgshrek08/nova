// Settings > Notes: Obsidian vaults Nova reads and writes, found
// automatically (app/obsidian_detect.py), connected with one click.
import { useCallback, useEffect, useState } from "react";
import { connectObsidianVault, detectObsidianVaults, disconnectObsidianVault, listObsidianVaults, selectDesktopFolder } from "../api.js";
import Icon from "./icons.jsx";
import { Row } from "./SettingsSections.jsx";
import { useUi } from "./ui.jsx";

const norm = (p) => String(p || "").replace(/[\\/]+$/, "").toLowerCase();

export default function ObsidianSettings() {
  const ui = useUi();
  const [connected, setConnected] = useState(null);
  const [found, setFound] = useState(null);
  const [busy, setBusy] = useState("");
  const load = useCallback(async () => {
    const [mine, detected] = await Promise.all([
      listObsidianVaults().catch(() => []),
      detectObsidianVaults().catch(() => ({ vaults: [] })),
    ]);
    const rows = Array.isArray(mine) ? mine : mine?.vaults || [];
    setConnected(rows);
    const have = new Set(rows.map((v) => norm(v.path)));
    setFound((detected.vaults || []).filter((v) => !have.has(norm(v.path))));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function connect(path, name) {
    setBusy(path);
    try { await connectObsidianVault(name || path.split(/[\\/]/).filter(Boolean).pop() || "Vault", path); ui.toast(`Nova now reads "${name || path}".`); await load(); }
    catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }
  const disconnect = (v) => ui.undoable({
    message: `Nova stopped reading "${v.name}". Your notes weren't touched.`,
    apply: () => setConnected((all) => all.filter((x) => x.id !== v.id)),
    revert: load,
    commit: () => disconnectObsidianVault(v.id).then(load),
  });

  return (
    <div className="p-sgroup">
      <div className="p-shead"><h4>Obsidian vaults</h4>
        <button className="p-link" onClick={load}><Icon name="refresh" size={13} /> Look again</button></div>
      <p className="d">Nova reads your notes to answer with what you already know, and can add notes when you ask. It finds vaults from Obsidian's own list and in your usual folders.</p>
      {connected === null && <div className="note">Looking for your vaults…</div>}
      {(connected || []).map((v) => (
        <Row key={v.id} label={v.name} desc={v.path}>
          <span className="p-status tested">connected</span>
          <button className="p-link" onClick={() => disconnect(v)} aria-label={`Stop reading ${v.name}`} title="Stop reading"><Icon name="x" size={14} /></button>
        </Row>
      ))}
      {(found || []).map((v) => (
        <Row key={v.path} label={v.name} desc={`${v.notes >= 5000 ? "5,000+" : v.notes.toLocaleString()} notes · ${v.is_open ? "open in Obsidian" : v.source === "found" ? "found on this computer" : "in Obsidian"} · ${v.path}`}>
          <button className="p-sm dark" disabled={busy === v.path} onClick={() => connect(v.path, v.name)}>{busy === v.path ? "Connecting…" : "Connect"}</button>
        </Row>
      ))}
      {connected && found && connected.length === 0 && found.length === 0 && <p className="note">No Obsidian vaults found on this computer.</p>}
      <div className="p-acts" style={{ marginTop: 8 }}>
        <button className="p-sm" onClick={async () => { const p = await selectDesktopFolder().catch(() => null); const path = p?.path || p; if (path) connect(path); }}><Icon name="folder" />Choose a vault folder…</button>
      </div>
    </div>
  );
}
