export const TEAM_LABEL = {
  engineering: "Engineering", design: "Design & Frontend", research: "Research",
  learning: "Learning", business: "Business & Planning", desktop: "Desktop & Browser",
  memory: "Memory & Knowledge", quality: "Quality & Performance",
  everyday: "Free Models / Everyday",
};
export function modelLabel(role, roles, { withTeam = true } = {}) {
  if (!role.model_id) return "Unassigned";
  const name = role.model_name || ({claude_cli:"Claude",claude_cli_plan:"Claude",codex_cli:"Codex",codex_cli_plan:"Codex",antigravity_cli:"Antigravity"}[role.model_id]) || role.model_id.replace(/^ollama:|^openrouter:/, "");
  // The team suffix disambiguates one model shared across teams -- useful in
  // Settings, where roles from every team sit in one list. Inside a panel
  // already titled with that team it is the heading repeated on every row,
  // which is what pushed these rows to two lines and clipped the panel.
  if (!withTeam) return name;
  const teams = new Set(roles.filter(r => r.model_id?.replace(/_plan(?=:|$)/, "") === role.model_id.replace(/_plan(?=:|$)/, "")).map(r => r.team).filter(Boolean));
  return teams.size > 1 ? `${name} -(${TEAM_LABEL[role.team] || "Director"})` : name;
}
