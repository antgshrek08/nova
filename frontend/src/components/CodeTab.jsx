import { useCallback, useEffect, useRef, useState } from "react";
import FileTree from "./FileTree.jsx";
import CodeEditor from "./CodeEditor.jsx";
import IdeTools, { ProjectActions } from "./IdeTools.jsx";
import EditorTabs from "./EditorTabs.jsx";
import Breadcrumbs from "./Breadcrumbs.jsx";
import ChangeReviewPanel from "./ChangeReviewPanel.jsx";
import ChatWindow from "./ChatWindow.jsx";
import LivePreviewPanel from "./ide/LivePreviewPanel.jsx";
import { BACKEND_URL, getCodeWorkspaceRoot, setCodeWorkspaceRoot, resetCodeWorkspaceRoot, createCodeFile } from "../api.js";
import {
  useOpenFiles,
  openFile,
  closeFile,
  closeAllFiles,
  setActiveFile,
  saveFile,
  addFileChangeSet,
  useFileChangeSets,
} from "../lib/codeEditorStore.js";
import { ChevronRightIcon, FolderOpenIcon } from "./icons.jsx";

const DEFAULT_CHAT_HEIGHT = 320;
const MIN_CHAT_HEIGHT = 160;
const MIN_EDITOR_HEIGHT = 160;
const EXPLORER_WIDTH = 224;

// Bottom-panel views, in display order. The divider falls before index
// BOTTOM_VIEW_DIVIDER, separating "what N.O.V.A. is doing here" from the
// project tooling -- one group of tabs, two readable halves.
const BOTTOM_VIEWS = [
  { id: "conversation", label: "Conversation" },
  { id: "changes", label: "Changes" },
  { id: "terminal", label: "Terminal" },
  { id: "git", label: "Git" },
  { id: "preview", label: "Preview" },
  // After Git and Preview on purpose: shipping is what you do once the code
  // is committed and you have seen it run.
  { id: "ship", label: "Ship" },
];
const BOTTOM_VIEW_DIVIDER = 2;

/** Code tab: a real desktop coding workspace (Code tab milestone). Layout:
 * a collapsible project/file explorer on the left; a main column with
 * open-file tabs + breadcrumbs above the editor; a resizable bottom panel
 * holding either the AI conversation or the change-review view. Open
 * files/tabs live in lib/codeEditorStore.js, not component state, so they
 * (and any unsaved edits) survive switching to Chat/Memory and back --
 * CodeTab itself still unmounts like any other App.jsx tab, but the store
 * doesn't (task: "Protection against losing edits when changing files or
 * app tabs"). */
export default function CodeTab({ conversationId, onResponseDone, onNewConversation, renderConversation }) {
  const { openPaths, activePath, getEntry, isDirty, dirtyPaths } = useOpenFiles();
  const changeSets = useFileChangeSets();
  const [treeRefreshKey, setTreeRefreshKey] = useState(0);
  const [chatHeight, setChatHeight] = useState(DEFAULT_CHAT_HEIGHT);
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [bottomView, setBottomView] = useState("conversation");
  const [workspaceRoot, setWorkspaceRoot] = useState(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [savingAll, setSavingAll] = useState(false);
  const [createRequest, setCreateRequest] = useState(0);
  const [splitPreview, setSplitPreview] = useState(() => new URLSearchParams(window.location.search).get("live") === "1");
  const draggingRef = useRef(false);
  const columnRef = useRef(null);

  useEffect(() => {
    getCodeWorkspaceRoot()
      .then(setWorkspaceRoot)
      .catch((err) => setWorkspaceError(err.message || "Couldn't reach N.O.V.A."));
  }, []);

  const handleDragMove = useCallback((e) => {
    if (!draggingRef.current || !columnRef.current) return;
    const rect = columnRef.current.getBoundingClientRect();
    const proposed = rect.bottom - e.clientY;
    const maxChatHeight = rect.height - MIN_EDITOR_HEIGHT;
    setChatHeight(Math.min(maxChatHeight, Math.max(MIN_CHAT_HEIGHT, proposed)));
  }, []);

  const handleDragEnd = useCallback(() => {
    draggingRef.current = false;
    document.body.style.cursor = "";
    window.removeEventListener("mousemove", handleDragMove);
    window.removeEventListener("mouseup", handleDragEnd);
  }, [handleDragMove]);

  function handleDragStart() {
    draggingRef.current = true;
    document.body.style.cursor = "row-resize";
    window.addEventListener("mousemove", handleDragMove);
    window.addEventListener("mouseup", handleDragEnd);
  }

  useEffect(() => () => handleDragEnd(), [handleDragEnd]);

  // Window-level (not CodeMirror-scoped) Ctrl+S: the editor's own DOM focus
  // is easy to lose without the user noticing -- clicking a conflict-dialog
  // button, a file-tree row, or any other control in the tab -- and a save
  // shortcut that silently does nothing once focus moves away is exactly
  // the kind of "lost edits" gap this milestone is supposed to close.
  useEffect(() => {
    function handleKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s" && !e.shiftKey) {
        e.preventDefault();
        if (activePath) saveFile(activePath);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activePath]);

  function handleSelectFile(path) {
    openFile(path);
  }

  async function handleCreateFile() {
    const path = window.prompt("New file path (for example src/index.ts):");
    if (!path?.trim()) return;
    const cleanPath = path.trim().replace(/\\/g, "/").replace(/^\/+/, "");
    try {
      await createCodeFile(cleanPath);
      setTreeRefreshKey((k) => k + 1);
      await openFile(cleanPath);
    } catch (err) {
      setWorkspaceError(err.message || "Couldn't create that file.");
    }
  }

  function handleCloseTab(path) {
    if (isDirty(path)) {
      const ok = window.confirm(`${path.split("/").pop()} has unsaved changes. Close it and discard them?`);
      if (!ok) return;
    }
    closeFile(path);
  }

  async function handleSaveAll() {
    setSavingAll(true);
    try {
      for (const path of dirtyPaths) {
        // eslint-disable-next-line no-await-in-loop -- each save can hit a
        // real conflict needing the user's own choice before the next one
        // should proceed; sequential is deliberate here, not an oversight.
        await saveFile(path);
      }
      setTreeRefreshKey((k) => k + 1);
    } finally {
      setSavingAll(false);
    }
  }

  // Open tabs are paths relative to whatever root they were opened under.
  // Left open across a root switch, saving one would silently write into
  // the *new* project at a same-named path with the *old* project's content
  // -- a real gap found live (a stale tab kept its old content while its
  // breadcrumb relabeled itself with the new root's name). Confirm before
  // discarding any unsaved edits, same as closing a single dirty tab.
  function confirmDiscardOpenTabs() {
    if (dirtyPaths.length === 0) return true;
    return window.confirm(
      `Switching projects will close ${openPaths.length} open tab(s), including ${dirtyPaths.length} with unsaved changes. Discard them?`
    );
  }

  async function handleChooseFolder() {
    setWorkspaceError("");
    let picked = null;
    if (window.electronAPI?.chooseProjectFolder) {
      picked = await window.electronAPI.chooseProjectFolder();
    } else {
      // Dev-in-Chrome fallback (no Electron native dialog available there)
      // -- a real, if less convenient, way to still exercise this feature
      // outside the packaged app.
      picked = window.prompt("Enter the full path to a project folder:");
    }
    if (!picked) return;
    if (!confirmDiscardOpenTabs()) return;
    try {
      const root = await setCodeWorkspaceRoot(picked);
      setWorkspaceRoot(root);
      closeAllFiles();
      setTreeRefreshKey((k) => k + 1);
    } catch (err) {
      setWorkspaceError(err.message || "Couldn't open that folder.");
    }
  }

  async function handleResetFolder() {
    if (!confirmDiscardOpenTabs()) return;
    try {
      const root = await resetCodeWorkspaceRoot();
      setWorkspaceRoot(root);
      closeAllFiles();
      setTreeRefreshKey((k) => k + 1);
    } catch (err) {
      setWorkspaceError(err.message || "Couldn't reset the project.");
    }
  }

  async function handleNovaSource() {
    if (!confirmDiscardOpenTabs()) return;
    try {
      const response = await fetch(`${BACKEND_URL}/code/nova-source`, { method: "POST" });
      const root = await response.json();
      if (!response.ok) throw new Error(root.detail || "Nova source unavailable");
      setWorkspaceRoot(root);
      closeAllFiles();
      setTreeRefreshKey(k => k + 1);
      setWorkspaceError("");
    } catch (error) { setWorkspaceError(error.message); }
  }

  const activeEntry = activePath ? getEntry(activePath) : null;
  const hasUnreviewedChanges = changeSets.length > 0;

  return (
    <div className="flex h-full min-h-0 min-w-0">
      {/* Collapsible project/file explorer (design direction). Collapsed
          state is a thin rail with just a reopen affordance, not fully
          gone -- consistent with the app's own NavRail always staying
          reachable. */}
      {explorerOpen ? (
        <div className="flex shrink-0 flex-col border-r border-charcoal-700 bg-charcoal-900" style={{ width: EXPLORER_WIDTH }}>
          <div className="flex shrink-0 items-center justify-between gap-1 border-b border-charcoal-800 px-2.5 py-2">
            <button
              onClick={() => setExplorerOpen(false)}
              title="Collapse explorer"
              className="flex shrink-0 items-center rounded p-1 text-charcoal-500 transition-colors hover:bg-charcoal-800 hover:text-charcoal-200"
            >
              <ChevronRightIcon className="h-3.5 w-3.5 rotate-180" />
            </button>
            <span className="min-w-0 flex-1 truncate text-center text-[11px] font-semibold uppercase tracking-wide text-charcoal-400" title={workspaceRoot?.path}>
              {workspaceRoot?.name || "Project"}
            </span>
            <button
              onClick={handleChooseFolder}
              title="Open a different project folder"
              className="flex shrink-0 items-center rounded p-1 text-charcoal-500 transition-colors hover:bg-charcoal-800 hover:text-emerald-300"
            >
              <FolderOpenIcon className="h-4 w-4" />
            </button>
          </div>
          {/* Muted, not emerald: this is a shortcut to one particular folder,
              not the main thing to do in this panel, and accent colour was
              making it the loudest element in the sidebar. */}
          <button onClick={handleNovaSource} className="px-2.5 py-1 text-left text-[11.5px] text-charcoal-400 transition-colors hover:text-emerald-300" title="Open Nova's editable source checkout">Open Nova source</button>
          {!workspaceRoot?.is_default && (
            <button
              onClick={handleResetFolder}
              className="shrink-0 border-b border-charcoal-800 px-2.5 py-1 text-left text-[10.5px] text-charcoal-500 hover:bg-charcoal-800 hover:text-charcoal-300"
            >
              ← Back to default sandbox
            </button>
          )}
          {workspaceError && <p className="shrink-0 border-b border-charcoal-800 px-2.5 py-1 text-[10.5px] text-rose-400">{workspaceError}</p>}
          <div className="min-h-0 flex-1">
            <ProjectActions activePath={activePath} dirty={dirtyPaths.length > 0} createRequest={createRequest} onChanged={async (path, renamed) => { if (renamed) closeAllFiles(); setTreeRefreshKey(k => k + 1); if (path) await openFile(path); }} />
            <FileTree selectedPath={activePath} onSelect={handleSelectFile} onCreateFile={() => setCreateRequest(k => k + 1)} refreshKey={treeRefreshKey} />
          </div>
        </div>
      ) : (
        <button
          onClick={() => setExplorerOpen(true)}
          title="Show project explorer"
          className="flex w-6 shrink-0 flex-col items-center border-r border-charcoal-700 bg-charcoal-900 py-2 text-charcoal-500 transition-colors hover:text-emerald-300"
        >
          <ChevronRightIcon className="h-3.5 w-3.5" />
        </button>
      )}

      <div ref={columnRef} className="flex min-w-0 flex-1 flex-col">
        <EditorTabs openPaths={openPaths} activePath={activePath} isDirty={isDirty} onSelect={setActiveFile} onClose={handleCloseTab} />
        <div className="flex shrink-0 items-center justify-between border-b border-charcoal-800 pr-2">
          <Breadcrumbs path={activePath} workspaceName={workspaceRoot?.name || "Project"} />
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSplitPreview((prev) => !prev)}
              title={splitPreview ? "Close Split Preview" : "Split-Screen Live Web Preview (localhost:3000)"}
              className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                splitPreview
                  ? "bg-emerald-600/20 text-emerald-300 ring-1 ring-emerald-500/50"
                  : "bg-charcoal-800 text-charcoal-300 hover:text-white ring-1 ring-charcoal-700"
              }`}
            >
              <span>⚡ Live Preview</span>
            </button>
            {dirtyPaths.length > 0 && (
              <button
                onClick={handleSaveAll}
                disabled={savingAll}
                title="Save all open files with unsaved changes"
                className="rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                {savingAll ? "Saving…" : `Save All (${dirtyPaths.length})`}
              </button>
            )}
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-row overflow-hidden">
          <div className="min-h-0 flex-1 overflow-hidden">
            <CodeEditor path={activePath} entry={activeEntry} projectKey={workspaceRoot?.path ?? ""} />
          </div>
          {splitPreview && (
            <div className="min-h-0 w-1/2 overflow-hidden flex flex-col">
              <LivePreviewPanel onClose={() => setSplitPreview(false)} />
            </div>
          )}
        </div>


        {/* Drag handle -- same "grab the divider" interaction as a real
            IDE's terminal panel, with a centered grip glyph so it reads as
            draggable rather than just a stray border line. */}
        <div
          onMouseDown={handleDragStart}
          className="flex h-1.5 shrink-0 cursor-row-resize items-center justify-center border-y border-charcoal-800 bg-charcoal-900 hover:bg-charcoal-800"
          title="Drag to resize"
        >
          <div className="h-0.5 w-8 rounded-full bg-charcoal-700" />
        </div>

        {/* Bottom-panel switcher. Every button here picks which view fills the
            panel below, so they belong in one group -- previously "+ New"
            (which creates a conversation, an entirely different kind of
            action) sat in the middle of them, splitting the five tabs into two
            halves that looked like unrelated controls. The tabs are now one
            run, ordered N.O.V.A.-first then tooling with a hairline between,
            and the one real action sits on the right where an action belongs,
            only while the view it acts on is showing. */}
        <div className="flex shrink-0 items-center gap-0.5 border-b border-charcoal-800 bg-charcoal-900 px-2 py-1.5">
          {BOTTOM_VIEWS.map((view, index) => (
            <div key={view.id} className="flex items-center">
              {index === BOTTOM_VIEW_DIVIDER && <span aria-hidden="true" className="mx-1.5 h-3.5 w-px bg-charcoal-700" />}
              <button
                onClick={() => setBottomView(view.id)}
                aria-pressed={bottomView === view.id}
                className={`relative rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  bottomView === view.id
                    ? "bg-emerald-600/20 text-emerald-300"
                    : "text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
                }`}
              >
                {view.label}
                {view.id === "changes" && hasUnreviewedChanges && bottomView !== "changes" && (
                  <span
                    title="Files changed since the last review"
                    className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-amber-400"
                  />
                )}
              </button>
            </div>
          ))}
          {bottomView === "conversation" && (
            <button
              onClick={onNewConversation}
              title="Start a new code conversation"
              className="ml-auto rounded-md px-2 py-1 text-[11px] font-medium text-charcoal-400 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 hover:text-charcoal-200"
            >
              + New
            </button>
          )}
        </div>
        <div className="min-h-0 shrink-0" style={{ height: chatHeight }}>
          {bottomView === "conversation" ? (
            renderConversation ? renderConversation({
              conversationId,
              onResponseDone,
              onFileChanges: (convId, changes) => {
                addFileChangeSet(convId, changes);
                setTreeRefreshKey((k) => k + 1);
              },
            }) : (
            <ChatWindow
              conversationId={conversationId}
              variant="code"
              onResponseDone={onResponseDone}
              onFileChanges={(convId, changes) => {
                addFileChangeSet(convId, changes);
                setTreeRefreshKey((k) => k + 1);
              }}
            />
            )
          ) : bottomView === "changes" ? (
            <ChangeReviewPanel onOpenFile={handleSelectFile} />
          ) : null}
          <IdeTools view={bottomView} workspace={workspaceRoot?.path} />
        </div>
      </div>
    </div>
  );
}
