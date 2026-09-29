import { useEffect, useRef, useState } from "react";
import { searchMemory, listMemory, updateMemory, deleteMemory } from "../../api.js";

const ROLE_LABEL = {
  user: { text: "You said", tone: "text-emerald-300 bg-emerald-900/30" },
  assistant: { text: "N.O.V.A. generated", tone: "text-sky-300 bg-sky-900/30" },
};

// Refinement pass (task: "Distinguish confirmed facts from unconfirmed
// candidates ... Remembered Facts should contain actual remembered
// assertions, preferences, and decisions ... not an unfiltered message
// archive"). Every tab here is a real, inspectable filter over the SAME
// data -- nothing is deleted or hidden from the user permanently, "All"
// always reaches everything (operational-error entries are the one
// exception: see the module note on TABS below, and graph.py's/memory.py's
// own docstrings for where that exclusion actually happens). "Confirmed" is
// the default because that's the closest thing to "an actual remembered
// assertion" this app can honestly claim -- see memory.py's
// classify_fact_status for exactly what earns that label and why an
// assistant reply never does on its own.
const TABS = [
  { id: "confirmed", label: "Confirmed" },
  { id: "unconfirmed", label: "Assistant output" },
  { id: "question", label: "Questions & requests" },
  { id: "all", label: "All" },
];

const STATUS_PILL = {
  confirmed: { text: "Confirmed", tone: "text-emerald-300 bg-emerald-900/40" },
  unconfirmed: { text: "Unconfirmed", tone: "text-charcoal-300 bg-charcoal-700" },
  question: { text: "Question", tone: "text-sky-300 bg-sky-900/30" },
};

/** One remembered fact -- content-sized card (task: "Use content-sized rows
 * or cards without large blank areas"), source/date/status/Edit/Forget kept
 * legible, routing category demoted to a title-only tooltip (task: "Move
 * low-level routing categories out of the primary visual hierarchy" -- this
 * is genuinely a routing concern, see main.py's CATEGORY_CHAINS, not
 * anything about the memory's own meaning). */
function FactRow({ entry, showStatusPill, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.content);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const role = ROLE_LABEL[entry.role] || { text: entry.role, tone: "text-charcoal-300 bg-charcoal-700" };
  const statusPill = showStatusPill ? STATUS_PILL[entry.fact_status] : null;

  async function handleSave() {
    if (!draft.trim()) { setError("A memory cannot be empty."); return; }
    setError("");
    setSaving(true);
    try {
      await updateMemory(entry.id, draft);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err.message || "Could not save this memory.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Forget this memory? This can't be undone. The original conversation message is not deleted.")) return;
    try {
      await deleteMemory(entry.id);
      onChanged();
    } catch (err) { setError(err.message || "Could not forget this memory."); }
  }

  return (
    <div className="min-w-0 rounded-lg border border-charcoal-700 bg-charcoal-850 px-3 py-2 text-sm">
      {error && <p role="alert" className="mb-2 text-xs text-rose-300">{error}</p>}
      <div className="mb-1.5 flex min-w-0 flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-charcoal-500">
          <span className={`shrink-0 rounded-full px-2 py-0.5 font-medium ${role.tone}`}>{role.text}</span>
          {statusPill && <span className={`shrink-0 rounded-full px-2 py-0.5 font-medium ${statusPill.tone}`}>{statusPill.text}</span>}
          <span className="shrink-0" title={entry.category ? `Routing category: ${entry.category}` : undefined}>
            {entry.date}
          </span>
          {entry.distance != null && <span className="shrink-0">match {(1 - entry.distance).toFixed(2)}</span>}
        </div>
        <div className="flex shrink-0 gap-2 text-xs">
          <button onClick={() => setEditing((e) => !e)} className="text-charcoal-400 hover:text-charcoal-200">
            {editing ? "Cancel" : "Correct"}
          </button>
          <button onClick={handleDelete} className="text-charcoal-400 hover:text-rose-400">
            Forget
          </button>
        </div>
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full min-w-0 resize-none rounded-md bg-charcoal-950 px-2.5 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-600 focus:ring-emerald-500"
          />
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save correction"}
          </button>
        </div>
      ) : (
        <p className="min-w-0 whitespace-pre-wrap break-words leading-relaxed text-charcoal-100">{entry.content}</p>
      )}
    </div>
  );
}

function formatDate(raw) {
  if (!raw) return "";
  if (raw === "source-deleted") return "source deleted";
  try {
    const normalized = raw.replace(" ", "T");
    return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : normalized + "Z").toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return raw;
  }
}

/** "Remembered Facts" -- search/browse/correct/forget, now with a real
 * status filter instead of one unfiltered archive (see TABS above). */
export default function FactsView() {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("confirmed");
  const [allEntries, setAllEntries] = useState([]);
  const [mode, setMode] = useState("browse");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestRef = useRef(0);

  async function refresh(searchQuery = mode === "search" ? query.trim() : "") {
    const request = ++requestRef.current;
    setLoading(true);
    setError("");
    try {
      const raw = searchQuery ? await searchMemory(searchQuery, 40) : await listMemory(200);
      if (request !== requestRef.current) return;
      setAllEntries(raw.map((e) => ({ ...e, date: formatDate(e.created_at) })));
    } catch (err) {
      // Backend-outage task (Milestone 2 verification): a fetch failure
      // isn't "nothing remembered yet" -- see the identical fix in
      // ConversationSidebar.jsx for the same reasoning.
      if (request === requestRef.current) setError(err.message || "Couldn't reach N.O.V.A.'s memory.");
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    return () => { requestRef.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSearch(e) {
    e.preventDefault();
    setMode(query.trim() ? 'search' : 'browse');
    await refresh(query.trim());
  }

  const entries = tab === "all" ? allEntries : allEntries.filter((e) => e.fact_status === tab);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col p-5">
      <form onSubmit={handleSearch} className="mb-3 flex min-w-0 shrink-0 gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search everything remembered across conversations…"
          className="min-w-0 flex-1 rounded-lg bg-charcoal-850 px-3.5 py-2 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-600 focus:ring-emerald-500"
        />
        <button
          type="submit"
          className="shrink-0 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          Search
        </button>
      </form>

      <div className="mb-3 flex shrink-0 flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              tab === t.id
                ? "bg-emerald-600 text-white"
                : "text-charcoal-400 ring-1 ring-charcoal-600 hover:bg-charcoal-800 hover:text-charcoal-200"
            }`}
          >
            {t.label}
            {t.id !== "all" && ` (${allEntries.filter((e) => e.fact_status === t.id).length})`}
          </button>
        ))}
      </div>

      <p className="mb-3 shrink-0 text-xs text-charcoal-500">
        {mode === "search" ? `Search results for "${query}"` : "Most recently remembered"}
      </p>

      <div className="min-h-0 min-w-0 flex-1 space-y-2 overflow-y-auto overflow-x-hidden">
        {loading && <p className="text-center text-sm text-charcoal-500">Loading…</p>}
        {!loading && error && (
          <div className="mt-16 text-center text-sm text-rose-400">Couldn't reach N.O.V.A.'s memory: {error}</div>
        )}
        {!loading && !error && entries.length === 0 && (
          <div className="mt-16 text-center text-sm text-charcoal-500">
            {mode === "search"
              ? "No matching memories in this filter."
              : tab === "confirmed"
                ? "No confirmed facts yet — they fill in as you make declarative statements N.O.V.A. can remember."
                : "Nothing here yet."}
          </div>
        )}
        {entries.map((entry) => (
          <FactRow key={entry.id} entry={entry} showStatusPill={tab === "all"} onChanged={refresh} />
        ))}
      </div>
    </div>
  );
}
