import { useEffect, useState } from "react";
import { listCodeTree } from "../api.js";
import { ChevronRightIcon, FileIcon, FolderIcon } from "./icons.jsx";

function TreeNode({ entry, depth, selectedPath, onSelect }) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState(null);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    if (!entry.is_dir) {
      onSelect(entry.path);
      return;
    }
    if (!expanded && children === null) {
      setLoading(true);
      try {
        setChildren(await listCodeTree(entry.path));
      } catch {
        setChildren([]);
      } finally {
        setLoading(false);
      }
    }
    setExpanded((e) => !e);
  }

  const isSelected = !entry.is_dir && selectedPath === entry.path;
  const indent = depth * 14 + 10;

  return (
    <div>
      <div
        onClick={toggle}
        style={{ paddingLeft: `${indent}px` }}
        className={`flex cursor-pointer items-center gap-1.5 py-1 pr-2 text-[13px] transition-colors ${
          isSelected ? "bg-emerald-500/10 text-emerald-300" : "text-charcoal-300 hover:bg-charcoal-800"
        }`}
        title={entry.path}
      >
        <span className="flex w-3 shrink-0 justify-center text-charcoal-600">
          {entry.is_dir && (
            <ChevronRightIcon
              className={`h-3 w-3 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
            />
          )}
        </span>
        <span className={`shrink-0 ${entry.is_dir ? "text-emerald-500/70" : "text-charcoal-500"}`}>
          {entry.is_dir ? <FolderIcon /> : <FileIcon />}
        </span>
        <span className="min-w-0 truncate">{entry.name}</span>
      </div>
      {expanded && (
        <div>
          {loading && (
            <p style={{ paddingLeft: `${indent + 14}px` }} className="py-1 text-[11px] text-charcoal-600">
              Loading…
            </p>
          )}
          {children?.map((child) => (
            <TreeNode key={child.path} entry={child} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
          ))}
          {children?.length === 0 && (
            <p style={{ paddingLeft: `${indent + 14}px` }} className="py-1 text-[11px] text-charcoal-600">
              Empty
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** Code tab's file explorer -- lazy per-directory expansion, same pattern
 * any real IDE file tree uses, rather than fetching the whole project
 * recursively up front. Rooted server-side at the current project (see
 * backend/app/code_files.py -- the default built-in sandbox until the user
 * opens a different real folder), so this tree is always a live view of
 * whatever's really there, including files the coding CLIs just wrote. */
export default function FileTree({ selectedPath, onSelect, refreshKey, onCreateFile }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    listCodeTree("")
      .then(setEntries)
      .catch((err) => setError(err.message || "Couldn't load the file list."))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  return (
    <div className="h-full overflow-y-auto py-1.5">
      {loading && <p className="px-3 py-1 text-xs text-charcoal-600">Loading…</p>}
      {!loading && error && <p className="px-3 py-1 text-xs text-rose-400">{error}</p>}
      {!loading && !error && entries.length === 0 && (
        <p className="px-3 py-1 text-xs leading-snug text-charcoal-600">
          No files yet — ask N.O.V.A. to create some, or open an existing project above.
        </p>
      )}
      {entries.map((entry) => (
        <TreeNode key={entry.path} entry={entry} depth={0} selectedPath={selectedPath} onSelect={onSelect} />
      ))}
      <button onClick={onCreateFile} className="mx-2 mt-3 w-[calc(100%-1rem)] rounded-md border border-dashed border-charcoal-600 px-2 py-1.5 text-left text-[11px] text-charcoal-400 hover:border-emerald-500/70 hover:text-emerald-300">
        + New file
      </button>
    </div>
  );
}
