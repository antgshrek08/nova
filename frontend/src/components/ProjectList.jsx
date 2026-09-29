import { useEffect, useState } from "react";
import { listProjects, createProject } from "../api.js";

export default function ProjectList({ onSelect, refreshKey }) {
  const [projects, setProjects] = useState([]);
  const [newName, setNewName] = useState("");

  async function refresh() {
    setProjects(await listProjects());
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    const project = await createProject({ name });
    setNewName("");
    await refresh();
    onSelect(project.id);
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-2">
      <div className="mb-2 flex gap-1">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          placeholder="New project name…"
          className="w-0 flex-1 rounded-md bg-charcoal-800 px-2 py-1 text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
        />
        <button
          onClick={handleCreate}
          className="shrink-0 rounded-md bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-500"
        >
          Add
        </button>
      </div>
      {projects.map((p) => (
        <div
          key={p.id}
          onClick={() => onSelect(p.id)}
          className="mb-1 cursor-pointer rounded-md px-2 py-1.5 text-xs text-charcoal-300 hover:bg-charcoal-800"
        >
          {p.name}
        </div>
      ))}
      {projects.length === 0 && (
        <p className="px-2 py-4 text-center text-xs text-charcoal-600">No projects yet.</p>
      )}
    </div>
  );
}
