import { useEffect, useState } from "react";
import { getMemoryGraphStatus, getLegacyMigrationStatus, applyLegacyMigration } from "../../api.js";

function StatusRow({ label, value, tone = "text-charcoal-200" }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-charcoal-800 py-2 text-sm last:border-0">
      <span className="text-charcoal-400">{label}</span>
      <span className={`text-right ${tone}`}>{value}</span>
    </div>
  );
}

/** Memory > Settings (task: "Remove the explanatory architecture paragraph
 * at the bottom of the Memory sidebar. Put relevant setup information in
 * Memory settings"). Real, live-checked status only -- nothing here is a
 * static claim about how the system is "supposed to" work. */
export default function SettingsView() {
  const [status, setStatus] = useState(null);
  const [migration, setMigration] = useState(null);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      const [s, m] = await Promise.all([getMemoryGraphStatus(), getLegacyMigrationStatus()]);
      setStatus(s);
      setMigration(m);
    } catch (err) {
      setError(err.message || "Couldn't reach N.O.V.A.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleApplyMigration() {
    setApplying(true);
    try {
      await applyLegacyMigration();
      await refresh();
    } catch (err) {
      setError(err.message || "Memory migration could not complete.");
    } finally {
      setApplying(false);
    }
  }

  if (error) {
    return <div className="p-5 text-sm text-rose-400">Couldn't reach N.O.V.A.: {error}</div>;
  }
  if (!status || !migration) {
    return <div className="p-5 text-sm text-charcoal-500">Loading…</div>;
  }

  const obsidian = status.obsidian || {};
  const pendingCount = migration.total - migration.already_tagged;

  return (
    <div className="h-full min-h-0 min-w-0 overflow-y-auto p-5">
      <div className="mx-auto max-w-xl space-y-6">
        <section>
          <h3 className="mb-2 text-sm font-semibold text-charcoal-100">Obsidian vault</h3>
          <div className="rounded-lg border border-charcoal-700 bg-charcoal-850 px-4 py-1">
            <StatusRow
              label="Vault folder"
              value={<span className="break-all font-mono text-[11px]">{obsidian.vault_dir}</span>}
            />
            <StatusRow
              label="Opened in Obsidian"
              value={obsidian.opened_in_obsidian ? "Yes" : "Not yet"}
              tone={obsidian.opened_in_obsidian ? "text-emerald-400" : "text-charcoal-400"}
            />
            <StatusRow
              label="Live plugin connection"
              value={obsidian.live_api_connected ? "Connected" : obsidian.api_key_configured ? "Configured, unreachable" : "Not connected"}
              tone={obsidian.live_api_connected ? "text-emerald-400" : "text-amber-400"}
            />
            <StatusRow label="Indexable notes found" value={obsidian.indexable_note_count} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-charcoal-500">
            {obsidian.live_api_connected
              ? "Notes you write directly in this vault are picked up automatically the next time the graph loads — no separate reindex step. Generated conversation/project notes and Graphify's own output are excluded so nothing gets indexed twice."
              : "Not connected: install and enable the Local REST API community plugin in Obsidian, then copy its API key into backend/.env as OBSIDIAN_API_KEY. Direct file sync (writing conversation/project notes to the vault folder above) still works either way; only live two-way editing needs the plugin. Changing the vault folder itself currently requires setting OBSIDIAN_VAULT_DIR in backend/.env and restarting the backend — no in-app folder picker yet."}
          </p>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-charcoal-100">Code indexing</h3>
          <div className="rounded-lg border border-charcoal-700 bg-charcoal-850 px-4 py-1">
            <StatusRow label="Graphify installed" value={status.graphify_installed ? "Yes" : "No"} />
            <StatusRow label="Nodes / edges indexed" value={`${status.graphify_total_nodes} / ${status.graphify_total_edges}`} />
            <StatusRow
              label="Local model for optional LLM features"
              value={status.local_model_available ? "Available" : "Not detected"}
              tone={status.local_model_available ? "text-emerald-400" : "text-charcoal-400"}
            />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-charcoal-500">
            Everything above runs with tree-sitter parsing only — no LLM call, local or paid, is required for
            code structure indexing. A local model only affects optional future features, never a fallback to
            a paid API.
          </p>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-charcoal-100">Legacy fact-status cleanup</h3>
          <div className="rounded-lg border border-charcoal-700 bg-charcoal-850 px-4 py-1">
            <StatusRow label="Total remembered entries" value={migration.total} />
            <StatusRow label="Already tagged" value={migration.already_tagged} />
            <StatusRow
              label="Pending"
              value={pendingCount}
              tone={pendingCount > 0 ? "text-amber-400" : "text-emerald-400"}
            />
          </div>
          <p className="mt-2 mb-2 text-xs leading-relaxed text-charcoal-500">
            One-time, fully reversible tag-only pass: classifies every remembered entry as an operational
            failure, a confirmed statement, a question, or unconfirmed assistant output, and backfills its real
            timestamp from the conversation record. Nothing is deleted — running this again is always safe.
          </p>
          <button
            onClick={handleApplyMigration}
            disabled={applying || pendingCount === 0}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {applying ? "Applying…" : pendingCount === 0 ? "Up to date" : `Tag ${pendingCount} pending entries`}
          </button>
        </section>
      </div>
    </div>
  );
}
