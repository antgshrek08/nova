import { useEffect, useState } from "react";
import {
  getProject,
  updateProject,
  listProjectFiles,
  uploadProjectFile,
  deleteProjectFile,
  projectFileDownloadUrl,
  createConversation,
  listConversations,
} from "../api.js";

export default function ProjectPanel({ projectId, onBack, onOpenConversation }) {
  const [project, setProject] = useState(null);
  const [instructions, setInstructions] = useState("");
  const [files, setFiles] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [saving, setSaving] = useState(false);

  async function refresh() {
    const p = await getProject(projectId);
    setProject(p);
    setInstructions(p.instructions || "");
    setFiles(await listProjectFiles(projectId));
    setConversations(await listConversations({ tab: "chat", projectId }));
  }

  async function handleNewConversation() {
    const conv = await createConversation({ tab: "chat", projectId, title: `${project.name} — chat` });
    onOpenConversation?.(conv.id);
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleSaveInstructions() {
    if (!project || instructions === project.instructions) return;
    setSaving(true);
    try {
      await updateProject(projectId, { instructions });
    } finally {
      setSaving(false);
    }
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadProjectFile(projectId, file);
    e.target.value = "";
    await refresh();
  }

  async function handleDeleteFile(fileId) {
    await deleteProjectFile(projectId, fileId);
    await refresh();
  }

  if (!project) return null;

  return (
    <div className="border-b border-charcoal-800 p-2 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <button onClick={onBack} className="text-charcoal-400 hover:text-charcoal-200">
          ← Projects
        </button>
        <span className="truncate font-medium text-charcoal-200">{project.name}</span>
      </div>

      <label className="mb-1 block text-charcoal-500">Project instructions</label>
      <textarea
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        onBlur={handleSaveInstructions}
        rows={3}
        placeholder="Instructions applied to every conversation in this project…"
        className="mb-1 w-full resize-none rounded-md bg-charcoal-800 px-2 py-1.5 text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
      />
      <p className="mb-2 h-3 text-charcoal-600">{saving ? "Saving…" : ""}</p>

      <label className="mb-1 block text-charcoal-500">Files</label>
      <div className="mb-2 space-y-1">
        {files.map((f) => (
          <div
            key={f.id}
            className="flex items-center justify-between rounded-md bg-charcoal-800/60 px-2 py-1"
          >
            <a
              href={projectFileDownloadUrl(projectId, f.id)}
              target="_blank"
              rel="noreferrer"
              className="truncate text-charcoal-300 hover:text-emerald-400"
            >
              {f.filename}
            </a>
            <button
              onClick={() => handleDeleteFile(f.id)}
              className="ml-2 shrink-0 text-charcoal-500 hover:text-rose-400"
            >
              ✕
            </button>
          </div>
        ))}
        {files.length === 0 && <p className="text-charcoal-600">No files attached.</p>}
      </div>
      <label className="mb-3 block cursor-pointer rounded-md border border-dashed border-charcoal-700 px-2 py-1.5 text-center text-charcoal-400 hover:border-charcoal-500 hover:text-charcoal-200">
        + Attach file
        <input type="file" className="hidden" onChange={handleFileChange} />
      </label>

      <label className="mb-1 block text-charcoal-500">Conversations ({conversations.length})</label>
      <div className="mb-2 space-y-1">
        {conversations.map((c) => (
          <div
            key={c.id}
            onClick={() => onOpenConversation?.(c.id)}
            className="cursor-pointer truncate rounded-md bg-charcoal-800/60 px-2 py-1 text-charcoal-300 hover:bg-charcoal-800 hover:text-emerald-300"
          >
            {c.title}
          </div>
        ))}
      </div>
      <button
        onClick={handleNewConversation}
        className="block w-full rounded-md border border-dashed border-charcoal-700 px-2 py-1.5 text-center text-charcoal-400 hover:border-charcoal-500 hover:text-charcoal-200"
      >
        + New conversation in this project
      </button>
    </div>
  );
}
