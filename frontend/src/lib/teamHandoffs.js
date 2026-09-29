const ASSIGNED = new Set(["queued", "blocked", "running"]);
const TERMINAL = new Set(["done", "partial", "error", "cancelled", "interrupted"]);

// The first snapshot seeds state; it never manufactures a new assignment.
export function taskHandoffs(previous, tasks, now) {
  if (!previous) return [];
  const events = [];
  for (const task of tasks) {
    if (!task.team || !task.parent_id) continue;
    const before = previous.get(task.id);
    if (before === task.status) continue;
    if ((!before || TERMINAL.has(before)) && ASSIGNED.has(task.status)) {
      events.push({ id: `${task.id}:${now}:out`, team: task.team, taskId: task.id, title: task.title, start: now, out: true, failed: false });
    } else if (before && ASSIGNED.has(before) && TERMINAL.has(task.status)) {
      events.push({ id: `${task.id}:${now}:in`, team: task.team, taskId: task.id, title: task.title, start: now, out: false, failed: !["done", "partial"].includes(task.status) });
    }
  }
  return events;
}
