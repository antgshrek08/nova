/** Live task state for the Workspace redesign (task: "Connect Workspace to
 * real job events"). Reuses the existing /ws/agents socket (agentSocket.js)
 * -- agents.py's AgentRegistry.broadcast_task (backend/app/agents.py) pushes
 * a {"type": "task", "task": {...db.py row...}} message on every real task
 * create/update, the same socket ModelNetwork/AgentWorkspace already use for
 * AgentJob events. No new websocket, no polling for the live parts -- only
 * the initial list comes from a real GET (the socket has no "give me
 * everything that existed before I connected" replay for tasks, unlike
 * AgentJob's own snapshot-on-connect).
 */
import { useEffect, useState } from "react";
import { connectAgentSocket } from "./agentSocket.js";
import { listWorkspaceTasks } from "../api.js";

const state = {
  tasksById: new Map(),
  loaded: false,
};
const listeners = new Set();

function notify() {
  listeners.forEach((fn) => fn());
}

function ingestTask(task) {
  state.tasksById.set(task.id, task);
}

let socketCleanup = null;
let refCount = 0;

function refetchAll() {
  listWorkspaceTasks()
    .then((tasks) => {
      tasks.forEach(ingestTask);
      state.loaded = true;
      notify();
    })
    .catch(() => {
      state.loaded = true;
      notify();
    });
}

function ensureConnected() {
  refCount += 1;
  if (socketCleanup) return;
  socketCleanup = connectAgentSocket(
    (msg) => {
      if (msg.type === "task") {
        ingestTask(msg.task);
        notify();
      }
    },
    // Refetch on every (re)connect, not just the first -- a broadcast only
    // reaches sockets connected at the moment it fires, so a client that
    // was briefly disconnected (a backend restart, this session's own most
    // common cause) could otherwise miss real state changes -- most
    // notably reconciliation's interrupted-task updates, which happen at
    // startup before this socket has necessarily reconnected yet.
    refetchAll
  );
}

function release() {
  refCount -= 1;
  if (refCount <= 0 && socketCleanup) {
    socketCleanup();
    socketCleanup = null;
    refCount = 0;
  }
}

/** All known tasks, newest-created first. Components filter/group
 * client-side (top-level vs subtask, by status, by team) -- the set is
 * small enough (this is a desktop app's own work queue, not a multi-tenant
 * backlog) that there's no real need for the backend to pre-group it. */
export function useTasks() {
  const [, forceRender] = useState(0);
  useEffect(() => {
    ensureConnected();
    const listener = () => forceRender((n) => n + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
      release();
    };
  }, []);
  const tasks = Array.from(state.tasksById.values()).sort((a, b) => b.id - a.id);
  return { tasks, loaded: state.loaded };
}

/** A version counter that changes whenever ANY task in the store changes --
 * cheap signal for a detail-view to know "refetch the full detail (activity/
 * dependencies/subtasks), something about this tree may have moved,"
 * without duplicating the detail shape (activity log, resolved
 * dependencies) into this store too. */
export function useTaskListVersion() {
  const { tasks } = useTasks();
  return tasks.reduce((acc, t) => acc + t.id * 1000 + new Date(t.updated_at).getTime() % 1000, 0);
}
