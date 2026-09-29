import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";
import { historyField } from "@codemirror/commands";
import { languageForPath } from "../lib/codeLanguage.js";
import { editorTheme, editorSyntaxHighlighting } from "../lib/codeMirrorTheme.js";
import {
  updateFileContent,
  saveFile,
  setFileConflict,
  reloadFileFromDisk,
  dismissSaveError,
  saveEditorHistory,
  takeEditorHistory,
} from "../lib/codeEditorStore.js";
import { FileIcon } from "./icons.jsx";

/** Editor foundation (task: "Inspect the existing file APIs and choose an
 * established free editor component that supports syntax highlighting,
 * search, undo/redo, keyboard shortcuts, and soft wrapping"). CodeMirror 6
 * via @uiw/react-codemirror -- a widely-used, actively maintained, MIT
 * React wrapper -- replaces the previous plain <textarea> + manual line-
 * number div. `basicSetup`'s defaults already cover search (Ctrl+F/Ctrl+H),
 * undo/redo (Ctrl+Z/Ctrl+Shift+Z), and the standard editing keymap;
 * `EditorView.lineWrapping` is what makes "no horizontal scrollbars" (task:
 * global requirement, explicitly superseding the earlier proposed editor
 * exception) hold for code too -- long lines wrap instead of scrolling. */
const EXTRA_EXTENSIONS = [EditorView.lineWrapping, editorTheme, editorSyntaxHighlighting];
const HISTORY_FIELDS = { history: historyField };

export default function CodeEditor({ path, entry, projectKey }) {
  const handleChange = useCallback(
    (value) => {
      if (path) updateFileContent(path, value);
    },
    [path]
  );

  // Undo/redo history (task: "Preserve each open file's editor history
  // across navigation to Chat, Memory, and Workspace and back. Scope it by
  // project and file identity"). @uiw/react-codemirror's own controlled
  // `value` prop swaps the document in place on an existing EditorView, so
  // switching between two open files previously shared ONE undo stack --
  // confirmed by inspection, not just a navigation-away problem. Keying the
  // element by (projectKey, path) forces a real remount -- a fresh
  // EditorState -- per file identity; `viewRef`/the effect below capture
  // that state's history (and selection/cursor, a free bonus of
  // EditorState.toJSON) right before each remount/unmount and hand it back
  // via `initialState` the next time this same identity mounts.
  const identityKey = `${projectKey ?? ""}::${path ?? ""}::${entry?.reloadGeneration ?? 0}`;
  const viewRef = useRef(null);
  useEffect(() => {
    const mountGeneration = entry?.reloadGeneration;
    return () => {
      const view = viewRef.current;
      // Skip the save if a reload happened during this mount (generation
      // bumped): `entry` is the same mutated object throughout, so this
      // comparison sees the post-reload value even though `mountGeneration`
      // was captured before it changed. Saving here would otherwise put the
      // pre-reload history right back where the next mount would find it,
      // undoing reloadFileFromDisk's own `entry.history = null`.
      if (view && path && entry && entry.reloadGeneration === mountGeneration) {
        saveEditorHistory(path, projectKey, view.state.toJSON(HISTORY_FIELDS));
      }
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately
    // re-runs (tearing down the previous identity's capture, arming a fresh
    // one) whenever identityKey changes, i.e. exactly on file/project switch
    // or a disk reload.
  }, [identityKey]);

  if (!path) {
    // The editor fills most of the tab, so a single centred sentence left a
    // large empty panel reading as "nothing loaded" rather than "ready".
    // A real empty state: what this pane is, how to fill it, and the one
    // shortcut worth knowing before you have a file open.
    return (
      <div className="flex h-full flex-col items-center justify-center px-6 text-center">
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-charcoal-800/70 text-charcoal-500 ring-1 ring-charcoal-700">
          <FileIcon className="h-5 w-5" />
        </div>
        <p className="text-[13px] font-medium text-charcoal-300">No file open</p>
        <p className="mt-1 max-w-xs text-[12px] leading-relaxed text-charcoal-500">
          Pick a file in the explorer to edit it, or ask N.O.V.A. in the conversation
          below to create one.
        </p>
        <p className="mt-3 text-[11px] text-charcoal-600">
          <kbd className="rounded border border-charcoal-700 bg-charcoal-800 px-1.5 py-0.5 font-mono text-[10px] text-charcoal-400">
            Ctrl
          </kbd>
          {" + "}
          <kbd className="rounded border border-charcoal-700 bg-charcoal-800 px-1.5 py-0.5 font-mono text-[10px] text-charcoal-400">
            S
          </kbd>{" "}
          saves from anywhere in this tab
        </p>
      </div>
    );
  }

  if (entry.loading) {
    return <div className="flex h-full items-center justify-center text-sm text-charcoal-500">Loading…</div>;
  }

  if (entry.notFound) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 px-8 text-center text-sm text-charcoal-500">
        <p>This file doesn't exist (it may have been deleted or renamed).</p>
        <p className="font-mono text-xs text-charcoal-600">{path}</p>
      </div>
    );
  }

  if (entry.error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <p className="text-sm text-rose-400">Couldn't open this file: {entry.error}</p>
      </div>
    );
  }

  const language = languageForPath(path);
  const extensions = language ? [...EXTRA_EXTENSIONS, language] : EXTRA_EXTENSIONS;
  const historyJSON = takeEditorHistory(path, projectKey);
  const initialState = historyJSON ? { json: historyJSON, fields: HISTORY_FIELDS } : undefined;

  return (
    <div className="relative flex h-full min-h-0 min-w-0 flex-col">
      {entry.saveError && (
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-rose-900/50 bg-rose-950/40 px-3 py-1.5 text-xs text-rose-300">
          <span className="truncate">Couldn't save: {entry.saveError}</span>
          <button onClick={() => dismissSaveError(path)} className="shrink-0 text-rose-400 hover:text-rose-200">
            Dismiss
          </button>
        </div>
      )}
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        <CodeMirror
          key={identityKey}
          value={entry.content}
          height="100%"
          theme="none"
          extensions={extensions}
          onChange={handleChange}
          initialState={initialState}
          onCreateEditor={(view) => {
            viewRef.current = view;
          }}
          basicSetup={{
            lineNumbers: true,
            foldGutter: true,
            highlightActiveLine: true,
            highlightActiveLineGutter: true,
            bracketMatching: true,
            closeBrackets: true,
            autocompletion: true,
            history: true,
            searchKeymap: true,
          }}
        />
      </div>

      {entry.conflict && (
        <ConflictDialog
          path={path}
          localContent={entry.content}
          currentContent={entry.conflict.currentContent}
          onOverwrite={() => saveFile(path, { force: true })}
          onReload={() => reloadFileFromDisk(path, entry.conflict.currentContent, entry.conflict.currentFingerprint)}
          onCancel={() => setFileConflict(path, null)}
        />
      )}
    </div>
  );
}

/** Task: "Never silently overwrite a file changed externally. Detect the
 * conflict and offer a clear comparison/reload/overwrite choice." A real
 * side-by-side compare (not just a warning) plus three explicit actions --
 * no default/implicit choice, since either one can lose real work. */
function ConflictDialog({ path, localContent, currentContent, onOverwrite, onReload, onCancel }) {
  // Portaled to document.body: CodeMirror's own autocomplete/search tooltips
  // are *also* appended directly to document.body (for cursor-relative
  // positioning), landing in the root stacking context regardless of this
  // component's original DOM position. A merely-local z-10 lost to that
  // tooltip in practice (confirmed live -- an autocomplete dropdown rendered
  // on top of this dialog); portaling puts both in the same root context so
  // a high z-index actually wins.
  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 p-4">
      <div className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-amber-700/50 bg-charcoal-900 shadow-2xl">
        <div className="shrink-0 border-b border-charcoal-700 px-4 py-3">
          <p className="text-sm font-medium text-amber-300">File changed outside the editor</p>
          <p className="mt-0.5 truncate font-mono text-xs text-charcoal-500">{path}</p>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-hidden bg-charcoal-700 sm:grid-cols-2">
          <div className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-charcoal-900">
            <p className="shrink-0 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-charcoal-500">
              Your version
            </p>
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words px-3 pb-3 font-mono text-[11px] leading-5 text-charcoal-300">
              {localContent}
            </pre>
          </div>
          <div className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-charcoal-900">
            <p className="shrink-0 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-charcoal-500">
              Current file on disk
            </p>
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words px-3 pb-3 font-mono text-[11px] leading-5 text-charcoal-300">
              {currentContent}
            </pre>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-charcoal-700 px-4 py-3">
          <button onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs font-medium text-charcoal-400 hover:text-charcoal-200">
            Cancel
          </button>
          <button
            onClick={onReload}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-charcoal-200 ring-1 ring-charcoal-600 hover:bg-charcoal-800"
          >
            Reload from disk (discard my edits)
          </button>
          <button
            onClick={onOverwrite}
            className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500"
          >
            Overwrite anyway
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
