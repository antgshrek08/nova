/** Open-file/tab state for the Code tab, kept outside React component state
 * so it survives CodeTab unmounting (task: "Protection against losing edits
 * when changing files or app tabs"). Same root cause and same fix pattern as
 * chatStreamStore.js: App.jsx's <main> is a strict either/or ternary between
 * Chat/Code/Workspace/Memory, so switching away from Code tab genuinely
 * unmounts it, not just hides it -- a plain useState for "which files are
 * open, with what unsaved edits" would be destroyed the instant someone
 * checks Chat or Memory and comes back. This is a single global workspace
 * (not per-conversation) -- there is one Code tab, one set of open files,
 * regardless of which conversation is active underneath it.
 */
import { useEffect, useState } from "react";
import { readCodeFile, saveCodeFile } from "../api.js";

/** @typedef {{ content: string, savedContent: string, fingerprint: string|null,
 *   loading: boolean, error: string, notFound: boolean, conflict: null | { currentContent: string, currentFingerprint: string } }} FileEntry */

const state = {
  openPaths: /** @type {string[]} */ ([]),
  activePath: /** @type {string|null} */ (null),
  files: /** @type {Map<string, FileEntry>} */ (new Map()),
};
const listeners = new Set();

function notify() {
  listeners.forEach((fn) => fn());
}

function emptyEntry() {
  return {
    content: "",
    savedContent: "",
    fingerprint: null,
    loading: false,
    error: "", // a real load failure -- nothing to edit, the editor pane shows this instead of content
    saveError: "", // a real save failure -- content is fine and stays editable; shown as a dismissable banner, not a takeover
    notFound: false,
    conflict: null,
    // Serialized CodeMirror undo/redo history (task: "Preserve each open
    // file's editor history across navigation to Chat, Memory, and
    // Workspace and back"), tagged with the project it was captured under
    // so a project switch can never restore one project's undo stack into
    // a same-named file in a different project. { projectKey, json } | null.
    history: null,
    // Bumped by reloadFileFromDisk. CodeEditor folds this into the live
    // EditorView's `key`, forcing a real remount (a fresh EditorState, not
    // just a new document swapped into the existing one) -- without this, a
    // disk-reload's content swap is itself just another entry in the SAME
    // live undo stack, and Ctrl+Z right after a reload undoes the reload
    // back to the pre-reload text (confirmed live: exactly the "restore
    // unrelated content" this task says a disk reload must never do).
    reloadGeneration: 0,
  };
}

function getEntry(path) {
  let entry = state.files.get(path);
  if (!entry) {
    entry = emptyEntry();
    state.files.set(path, entry);
  }
  return entry;
}

function isDirty(path) {
  const entry = state.files.get(path);
  return Boolean(entry && entry.content !== entry.savedContent);
}

/** Opens a file as a new tab (or focuses it if already open) and loads its
 * real content + fingerprint from the backend the first time. Re-selecting
 * an already-open, already-loaded tab is a no-op fetch -- its in-memory
 * (possibly unsaved) content is what should show, never re-clobbered by a
 * fresh read. */
export async function openFile(path) {
  if (!state.openPaths.includes(path)) {
    state.openPaths = [...state.openPaths, path];
  }
  state.activePath = path;
  const existing = state.files.get(path);
  notify();
  if (existing) return; // already loaded (or loading) this session

  const entry = getEntry(path);
  entry.loading = true;
  notify();
  try {
    const data = await readCodeFile(path);
    const fresh = getEntry(path); // re-fetch in case closed/changed while awaiting
    fresh.content = data.content;
    fresh.savedContent = data.content;
    fresh.fingerprint = data.fingerprint;
    fresh.loading = false;
    fresh.notFound = false;
    fresh.error = "";
  } catch (err) {
    const fresh = getEntry(path);
    fresh.loading = false;
    fresh.notFound = err.status === 404;
    fresh.error = err.message || "Couldn't load this file.";
  }
  notify();
}

/** Closes a tab. Task: "Protection against losing edits when changing
 * files" -- callers must confirm with the user first if isDirty(path); this
 * function itself always closes (the confirmation is a UI concern, kept in
 * the component so it can show a real dialog, not a bare window.confirm
 * buried in a store). */
export function closeFile(path) {
  state.openPaths = state.openPaths.filter((p) => p !== path);
  state.files.delete(path);
  if (state.activePath === path) {
    state.activePath = state.openPaths[state.openPaths.length - 1] ?? null;
  }
  notify();
}

export function setActiveFile(path) {
  state.activePath = path;
  notify();
}

/** Closes every open tab at once -- specifically for switching the project
 * root (task: "Opening an existing project through the native folder
 * picker"). Open tabs' paths are relative to whatever root they were opened
 * under; left open across a root switch, saving one would silently write
 * into the *new* project at a same-named path that has nothing to do with
 * the file the user actually meant (confirmed live: switching projects left
 * a stale tab whose breadcrumb relabeled itself with the new root's name
 * while still holding the old project's content). Callers must confirm with
 * the user first if any tab isDirty, same division of responsibility as
 * closeFile. */
export function closeAllFiles() {
  state.openPaths = [];
  state.activePath = null;
  state.files.clear();
  notify();
}

export function updateFileContent(path, content) {
  const entry = getEntry(path);
  entry.content = content;
  notify();
}

export function markFileSaved(path, fingerprint) {
  const entry = getEntry(path);
  entry.savedContent = entry.content;
  entry.fingerprint = fingerprint;
  entry.conflict = null;
  notify();
}

export function setFileConflict(path, conflict) {
  const entry = getEntry(path);
  entry.conflict = conflict; // { currentContent, currentFingerprint } or null to dismiss
  notify();
}

/** "Reload" side of the conflict dialog -- discards local edits, adopts the
 * file's real current on-disk content/fingerprint as the new baseline. Also
 * drops any saved undo history: task: "Do not retain history across a disk
 * reload ... where it could restore unrelated content" -- an undo stack
 * built against the pre-reload text could otherwise "undo" back into
 * content that no longer corresponds to what's really on disk. */
export function reloadFileFromDisk(path, content, fingerprint) {
  const entry = getEntry(path);
  entry.content = content;
  entry.savedContent = content;
  entry.fingerprint = fingerprint;
  entry.conflict = null;
  entry.history = null;
  entry.reloadGeneration += 1;
  notify();
}

/** Captures the editor's live undo/redo history (task: "Preserve each open
 * file's editor history across navigation ... and back") -- called right
 * before the editor unmounts (switching files, or leaving the Code app-tab
 * entirely), not on every keystroke, so this is one cheap serialization per
 * navigation rather than a per-edit cost. `projectKey` identifies the
 * project this file was open under, so history for a same-named file in a
 * *different* project can never be mistaken for this one's (task: "Scope it
 * by project and file identity"). No `notify()` -- this doesn't affect any
 * rendered state, only what the next mount of this same file will see. */
export function saveEditorHistory(path, projectKey, json) {
  const entry = state.files.get(path);
  if (!entry) return; // tab was closed (and its content discarded) before unmount ran
  entry.history = { projectKey, json };
}

/** Returns the saved history JSON for (path, projectKey) if both the file
 * and the project match what it was captured under, else null -- a project
 * switch or a disk reload (see reloadFileFromDisk) must never hand back a
 * stale/unrelated history to restore. */
export function takeEditorHistory(path, projectKey) {
  const entry = state.files.get(path);
  if (!entry || !entry.history) return null;
  if (entry.history.projectKey !== projectKey) return null;
  return entry.history.json;
}

export function getDirtyPaths() {
  return state.openPaths.filter(isDirty);
}

/** The one real save path -- used by CodeEditor's Ctrl+S, its Save button,
 * and CodeTab's "Save All", so there's exactly one place that calls the
 * API and updates the store (task: "Save and Save All" -- Save All is just
 * this, looped over every dirty tab, not a separate implementation).
 * Returns "saved" | "conflict" | "error" (with `entry.error` set for the
 * last case) rather than throwing, so a Save-All loop can keep going
 * through the rest of the tabs after one file hits a real backend error. */
export async function saveFile(path, { force = false } = {}) {
  const entry = getEntry(path);
  entry.saveError = "";
  try {
    const result = await saveCodeFile(path, entry.content, { expectedFingerprint: entry.fingerprint, force });
    markFileSaved(path, result.fingerprint);
    return "saved";
  } catch (err) {
    if (err.status === 409 && err.conflict) {
      setFileConflict(path, { currentContent: err.conflict.currentContent, currentFingerprint: err.conflict.currentFingerprint });
      return "conflict";
    }
    entry.saveError = err.message || "Couldn't save this file.";
    notify();
    return "error";
  }
}

export function dismissSaveError(path) {
  const entry = getEntry(path);
  entry.saveError = "";
  notify();
}

// --- change review (task: "Provide a change-review view for proposed
// edits") -------------------------------------------------------------
//
// Populated from the /chat stream's real `file_changes` NDJSON event (see
// main.py -- emitted only after a claude_cli/codex_cli turn that actually
// touched files, with a real unified diff per file already computed
// server-side from a genuine before/after snapshot). Kept here, not in
// ChatWindow's own per-conversation message list, so it survives switching
// away from Chat's Code-tab view and back the same way open files do; a
// dedicated Changes view reads this, not the transcript.

let fileChangeSets = []; // [{ id, conversationId, timestamp, changes: [...] }], most recent first

export function addFileChangeSet(conversationId, changes) {
  fileChangeSets = [{ id: `${Date.now()}-${Math.random()}`, conversationId, timestamp: Date.now(), changes }, ...fileChangeSets];
  notify();
}

export function getFileChangeSets() {
  return fileChangeSets;
}

export function clearFileChangeSets() {
  fileChangeSets = [];
  notify();
}

/** Real revert -- writes the captured "before" content straight back,
 * force=true since reverting IS the user's explicit, informed overwrite
 * (task: "Apply/reject actions only where backed by a real implementation"
 * -- this one is: the exact prior text is genuinely in hand, not guessed).
 * Also updates any currently-open tab for that same path so the editor
 * reflects the revert immediately instead of showing stale content until
 * the file is reopened. */
export async function revertChange(path, beforeContent) {
  const result = await saveCodeFile(path, beforeContent, { force: true });
  if (state.files.has(path)) {
    reloadFileFromDisk(path, beforeContent, result.fingerprint);
  }
  return result;
}

export function useFileChangeSets() {
  const [, forceRender] = useState(0);
  useEffect(() => {
    const listener = () => forceRender((n) => n + 1);
    listeners.add(listener);
    return () => listeners.delete(listener);
  }, []);
  return fileChangeSets;
}

export function getFileEntry(path) {
  return state.files.get(path) ?? emptyEntry();
}

/** Subscribes a component to every change in open-file state (paths, active
 * tab, or any file's content/dirty/conflict status) -- one hook, since
 * EditorTabs/breadcrumbs/CodeEditor/Save-All all need to react to the same
 * shared state and re-rendering all of them together is simpler and no more
 * expensive than fragmenting into several narrower hooks here. */
export function useOpenFiles() {
  const [, forceRender] = useState(0);
  useEffect(() => {
    const listener = () => forceRender((n) => n + 1);
    listeners.add(listener);
    return () => listeners.delete(listener);
  }, []);
  return {
    openPaths: state.openPaths,
    activePath: state.activePath,
    getEntry: getFileEntry,
    isDirty,
    dirtyPaths: getDirtyPaths(),
  };
}
