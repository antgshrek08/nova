import { useEffect, useState } from "react";
import { listTeams, setTeamRoleModel, setMaxHeavyWorkers } from "../../api.js";
import { TEAM_LABEL, modelLabel } from "../../lib/teamRoster.js";


function groupRoles(roles) {
  const groups = new Map();
  for (const role of roles) {
    const key = role.team || "director";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(role);
  }
  return groups;
}

/** Task: "A Teams view shows configured roles and their current
 * assignments" + "Allow provider/model assignments in Settings" -- this
 * page reads the same real /workspace/teams data Settings could also
 * surface; editing here calls the identical endpoint. Every role's
 * tool_scope is shown verbatim (teams.py's own honest description of what
 * that role can and can't do), not a decorative capability list. */
export default function TeamsView() {
  const [data, setData] = useState(null);
  const [models, setModelsState] = useState([]);
  const [savingKey, setSavingKey] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listTeams().then(d => {setData(d);setModelsState(d.model_options || []);}).catch((err) => setError(err.message || "Couldn't load teams."));
  }, []);

  async function handleModelChange(roleKey, modelId) {
    setSavingKey(roleKey);
    setError("");
    try {
      await setTeamRoleModel(roleKey, modelId || null);
      const fresh = await listTeams();
      setData(fresh);
      window.dispatchEvent(new Event("nova:teams-updated"));
    } catch (err) {
      setError(err.message || "Couldn't update this role's model.");
    } finally {
      setSavingKey(null);
    }
  }

  async function handleWorkerLimitChange(n) {
    try {
      await setMaxHeavyWorkers(n);
      const fresh = await listTeams();
      setData(fresh);
    } catch (err) {
      setError(err.message || "Couldn't update the worker limit.");
    }
  }

  if (error && !data) {
    return <p className="p-6 text-sm text-rose-400">{error}</p>;
  }
  if (!data) {
    return <p className="p-6 text-sm text-charcoal-500">Loading teams…</p>;
  }

  const groups = groupRoles(data.roles);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-md bg-charcoal-900 px-4 py-3 ring-1 ring-charcoal-800">
        <div>
          <p className="text-[13px] text-charcoal-200">Heavy workers</p>
          <p className="text-[11px] text-charcoal-500">
            Specialist teams share local and subscription providers. Everyday Models uses OpenRouter's free router. One local request runs at a time; cloud roles share account quotas.
          </p>
        </div>
        <select
          value={data.max_heavy_workers}
          onChange={(e) => handleWorkerLimitChange(Number(e.target.value))}
          className="ml-auto rounded-md bg-charcoal-800 px-2 py-1.5 text-[12px] text-charcoal-200 ring-1 ring-charcoal-700"
        >
          {[1, 2, 3, 4].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      {error && <p className="mb-3 text-[12px] text-rose-400">{error}</p>}

      {Array.from(groups.entries()).map(([team, roles]) => (
        <div key={team} className="mb-5">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-charcoal-500">
            {team === "director" ? "Director" : TEAM_LABEL[team] || team}
          </p>
          <div className="divide-y divide-charcoal-800/60 rounded-md ring-1 ring-charcoal-800">
            {roles.map((role) => (
              <div key={role.key} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] text-charcoal-200">{role.label}</p>
                  <p className="mt-0.5 text-[11px] text-charcoal-500">{role.tool_scope}</p>
                  <p className="mt-0.5 break-words text-[11px] text-charcoal-300">{modelLabel(role,data.roles)}</p>
                  <p className={`text-[11px] ${role.available ? "text-charcoal-500" : "text-amber-300"}`}>{role.availability_reason}</p>
                </div>
                <select
                  value={role.model_id}
                  onChange={(e) => handleModelChange(role.key, e.target.value)}
                  disabled={savingKey === role.key}
                  className="max-w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-[12px] text-charcoal-200 ring-1 ring-charcoal-700 disabled:opacity-50"
                >
                  <option value={role.default_model_id}>
                    {models.find(m => m.id === role.default_model_id)?.name || role.default_model_id || "Unassigned"} {!role.overridden ? "(default)" : ""}
                  </option>
                  {role.overridden && role.model_id !== role.default_model_id && !models.some(m=>m.id===role.model_id) && <option value={role.model_id}>{role.model_id} (unavailable)</option>}
                  {models
                    .filter((m) => m.enabled && m.id !== role.default_model_id)
                    .map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                </select>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
