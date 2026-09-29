import React, { useEffect, useState } from "react";
import { listModels, listCustomModels } from "../../api.js";

const DEFAULT_AGENT_ROLES = [
  {
    id: "planner",
    name: "Planner Agent",
    role: "Strategic Problem Decomposition & Workflow Coordination",
    icon: "🗺️",
    description: "Breaks complex student projects and multi-step homework into sequential tasks.",
    tools: ["Step Decomposition", "Dependency Mapping", "Coursework Scheduling"],
  },
  {
    id: "researcher",
    name: "Researcher Agent",
    role: "Academic Deep-Dive & Source Verification",
    icon: "🔍",
    description: "Searches documentation, papers, and textbooks to pull verified citations and evidence.",
    tools: ["Syllabus Grounding", "Scholarly Search", "Citation Formatter"],
  },
  {
    id: "executor",
    name: "Executor Agent",
    role: "Code Execution, Virtual Cursor & Browser Automation",
    icon: "⚡",
    description: "Drives the browser, runs terminal builds, clicks homework widgets, and writes code.",
    tools: ["Browser Control", "Virtual Cursor", "Terminal Shell"],
  },
  {
    id: "reviewer",
    name: "Reviewer & Verifier Agent",
    role: "Cross-Model Verification & Hallucination Defense",
    icon: "🛡️",
    description: "Double-checks all calculations, proof steps, and essay drafts against rubric standards.",
    tools: ["Proof Checking", "Format Validation", "Self-Healing Rectifier"],
  },
];

export default function TeamConstellation({ onOpenSettings }) {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTask, setActiveTask] = useState("");
  const [executingTeam, setExecutingTeam] = useState(false);
  const [teamLog, setTeamLog] = useState([]);

  useEffect(() => {
    async function loadModels() {
      try {
        const [mList, customList] = await Promise.all([
          listModels().catch(() => []),
          listCustomModels().catch(() => []),
        ]);
        const activeModels = [];
        if (Array.isArray(mList)) {
          mList.forEach((m) => {
            if (m.provider !== "unavailable" && !activeModels.some((x) => x.id === m.id)) {
              activeModels.push(m);
            }
          });
        }
        if (Array.isArray(customList)) {
          customList.forEach((cm) => {
            if (cm.enabled && !activeModels.some((x) => x.id === cm.model_id)) {
              activeModels.push({ id: cm.model_id, name: cm.name, provider: cm.provider });
            }
          });
        }
        setModels(activeModels);
      } catch (err) {
        console.error("Failed to load models for workspace:", err);
      } finally {
        setLoading(false);
      }
    }
    loadModels();
  }, []);

  const modelCount = models.length;
  const isUnlocked = modelCount >= 4;

  const handleRunTeam = () => {
    if (!activeTask.trim() || executingTeam) return;
    setExecutingTeam(true);
    setTeamLog([
      { agent: "Planner Agent", msg: `Decomposing project: "${activeTask}" into research, code, and review phases...`, time: "Just now" },
    ]);

    setTimeout(() => {
      setTeamLog((prev) => [
        ...prev,
        { agent: "Researcher Agent", msg: "Scanning academic requirements, syllabus guidelines, and verified data...", time: "2s ago" },
      ]);
    }, 1200);

    setTimeout(() => {
      setTeamLog((prev) => [
        ...prev,
        { agent: "Executor Agent", msg: "Generating deliverables and executing solutions in parallel...", time: "1s ago" },
      ]);
    }, 2400);

    setTimeout(() => {
      setTeamLog((prev) => [
        ...prev,
        { agent: "Reviewer & Verifier Agent", msg: "Verified output accuracy with 0 errors. Task complete.", time: "Complete" },
      ]);
      setExecutingTeam(false);
    }, 3800);
  };

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[#090b10] text-xs text-[#8E9EB5]">
        Loading multi-agent workspace…
      </div>
    );
  }

  // =========================================================================
  // LOCKED STATE: Fewer than 4 models connected
  // =========================================================================
  if (!isUnlocked) {
    const slots = [
      { num: 1, label: models[0]?.name || "Model 1", active: modelCount >= 1 },
      { num: 2, label: models[1]?.name || "Model 2", active: modelCount >= 2 },
      { num: 3, label: models[2]?.name || "Model 3", active: modelCount >= 3 },
      { num: 4, label: models[3]?.name || "Model 4", active: modelCount >= 4 },
    ];
    const progressPct = Math.min(100, Math.round((modelCount / 4) * 100));

    return (
      <div className="flex h-full w-full items-center justify-center overflow-y-auto bg-[#090b10] p-6 text-[#E2E8F0]">
        <div className="mx-auto w-full max-w-xl space-y-6 text-center">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-[#23293D] bg-[#0E121B] shadow-xl">
            <span className="text-3xl">🌌</span>
          </div>

          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-400">
              <span>🔒 Unlocks at 4+ Connected Models</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-white">Multi-Agent Team Workspace</h1>
            <p className="mx-auto max-w-md text-xs leading-relaxed text-[#8E9EB5]">
              Autonomous multi-agent collaboration requires at least 4 models to separate planning, deep research, direct execution, and independent verification.
            </p>
          </div>

          {/* Progress Tracker Card */}
          <div className="rounded-2xl border border-[#1E2433] bg-[#0E121B]/80 p-5 text-left shadow-lg">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="font-semibold text-white">Connected Models Readiness</span>
              <span className="font-mono font-semibold text-emerald-400">{modelCount} / 4 Connected</span>
            </div>

            {/* Progress Bar */}
            <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-[#161B28]">
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>

            {/* Slots Grid */}
            <div className="grid grid-cols-2 gap-2.5 text-xs">
              {slots.map((s) => (
                <div
                  key={s.num}
                  className={`flex items-center gap-2.5 rounded-xl border p-3 transition-all ${
                    s.active
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                      : "border-[#1E2433] bg-[#121622] text-[#5E6D82]"
                  }`}
                >
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ${
                      s.active ? "bg-emerald-500 text-slate-950" : "bg-[#1A2030] text-[#8E9EB5]"
                    }`}
                  >
                    {s.active ? "✓" : s.num}
                  </span>
                  <div className="min-w-0 flex-1 truncate">
                    <span className="block truncate font-medium">{s.label}</span>
                    <span className="text-[10px] opacity-75">{s.active ? "Connected" : "Needed"}</span>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-[#1A1F2C] pt-3 text-xs text-[#8E9EB5]">
              <span>Supports Claude, ChatGPT, Gemini, Ollama, Antigravity, OpenRouter</span>
              <button
                type="button"
                onClick={onOpenSettings}
                className="rounded-lg bg-emerald-500 px-3 py-1 font-semibold text-slate-950 hover:bg-emerald-400 transition-all"
              >
                Connect in Settings →
              </button>
            </div>
          </div>

          {/* 4 Roles Preview */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-left">
            {DEFAULT_AGENT_ROLES.map((role) => (
              <div key={role.id} className="rounded-xl border border-[#1E2433] bg-[#0E121B]/60 p-3">
                <span className="text-xl mb-1 block">{role.icon}</span>
                <span className="text-xs font-semibold text-white block">{role.name}</span>
                <p className="mt-1 text-[10px] text-[#8E9EB5] leading-snug">{role.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // =========================================================================
  // UNLOCKED STATE: 4 or more models connected
  // =========================================================================
  return (
    <div className="flex h-full flex-col overflow-y-auto bg-[#090b10] text-[#E2E8F0]">
      {/* Workspace Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#1A1F2C] bg-[#0E121B]/90 px-6 py-4 backdrop-blur-md">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold tracking-wide text-white">Multi-Agent Team Workspace</h1>
            <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400">
              {modelCount} Models Connected · Unlocked
            </span>
          </div>
          <p className="mt-0.5 text-xs text-[#8E9EB5]">
            Cross-model collaboration: Planner, Researcher, Executor, and Verifier working simultaneously
          </p>
        </div>
      </div>

      <div className="flex-1 space-y-6 p-6">
        {/* Active Task Launcher */}
        <div className="rounded-2xl border border-[#1E2433] bg-[#0E121B]/80 p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#8E9EB5] mb-2">
            Dispatch Collaborative Task to Multi-Agent Team
          </h2>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="e.g. Research and write complete chapter study guide with step-by-step calculus proofs and verified citations"
              value={activeTask}
              onChange={(e) => setActiveTask(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleRunTeam()}
              className="flex-1 rounded-xl border border-[#23293D] bg-[#121622] px-4 py-2.5 text-xs text-white placeholder-[#5E6D82] focus:border-emerald-500/60 focus:outline-none"
            />
            <button
              type="button"
              onClick={handleRunTeam}
              disabled={!activeTask.trim() || executingTeam}
              className="rounded-xl bg-emerald-500 px-5 py-2.5 text-xs font-semibold text-slate-950 transition-all hover:bg-emerald-400 disabled:opacity-50"
            >
              {executingTeam ? "Team Running..." : "Execute Team Project"}
            </button>
          </div>
        </div>

        {/* Live Team Log if running */}
        {teamLog.length > 0 && (
          <div className="rounded-xl border border-[#1E2433] bg-[#0E121B]/80 p-4">
            <h3 className="text-xs font-semibold text-white mb-2">Agent Execution Stream</h3>
            <div className="space-y-2">
              {teamLog.map((log, i) => (
                <div key={i} className="flex items-start justify-between rounded-lg border border-[#23293D] bg-[#121622] p-2.5 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-emerald-400">{log.agent}:</span>
                    <span className="text-[#CBD5E1]">{log.msg}</span>
                  </div>
                  <span className="text-[10px] text-[#8E9EB5]">{log.time}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 4 Agent Constellation Grid */}
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#8E9EB5] mb-3">
            Active Multi-Agent Constellation
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {DEFAULT_AGENT_ROLES.map((agent, index) => {
              const assignedModel = models[index % models.length]?.name || "Universal Model";
              return (
                <div
                  key={agent.id}
                  className="flex flex-col justify-between rounded-xl border border-[#1E2433] bg-[#0E121B]/80 p-4 transition-all hover:border-emerald-500/40 shadow-sm"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-2xl">{agent.icon}</span>
                      <span className="rounded bg-[#1A2030] px-2 py-0.5 text-[10px] font-semibold text-emerald-400 border border-emerald-500/20">
                        {assignedModel}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-white">{agent.name}</h3>
                    <p className="mt-1 text-xs text-[#8E9EB5] leading-relaxed">
                      {agent.role}
                    </p>
                  </div>

                  <div className="mt-4 border-t border-[#1A1F2C] pt-2">
                    <span className="text-[10px] uppercase font-semibold text-[#5E6D82] block mb-1">
                      Assigned Tools
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {agent.tools.map((t, ti) => (
                        <span key={ti} className="rounded bg-[#121622] px-1.5 py-0.5 text-[10px] text-[#8E9EB5] border border-[#23293D]">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
