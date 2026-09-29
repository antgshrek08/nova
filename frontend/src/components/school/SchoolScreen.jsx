import React, { useState, useEffect, useCallback } from "react";
import {
  listCourses,
  createCourse,
  deleteCourse,
  listAssignments,
  getCanvasStatus,
  runCanvasSync,
  getAppSettings,
  updateAppSettings,
} from "../../api.js";

export default function SchoolScreen({ onOpenChatWithPrompt }) {
  const [courses, setCourses] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [canvasStatus, setCanvasStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [homeworkMode, setHomeworkMode] = useState("tutor"); // "tutor" | "solve"

  // Add course modal state
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newInstructor, setNewInstructor] = useState("");
  const [newPortal, setNewPortal] = useState("Canvas LMS");
  const [newSchedule, setNewSchedule] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [cList, aList, cStat, settings] = await Promise.all([
        listCourses().catch(() => []),
        listAssignments().catch(() => []),
        getCanvasStatus().catch(() => null),
        getAppSettings().catch(() => null),
      ]);
      setCourses(cList || []);
      setAssignments(aList || []);
      setCanvasStatus(cStat);
      if (settings?.homework_mode) setHomeworkMode(settings.homework_mode);
    } catch (err) {
      console.error("Failed to load school data:", err);
      setError("Unable to load academic portal data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleToggleHomeworkMode = async (mode) => {
    setHomeworkMode(mode);
    try {
      await updateAppSettings({ homework_mode: mode });
    } catch {}
  };

  const handleSyncPortals = async () => {
    setSyncing(true);
    setError("");
    try {
      await runCanvasSync();
      await loadData();
    } catch (err) {
      setError(err.message || "Portal sync failed. Please check portal credentials in Settings.");
    } finally {
      setSyncing(false);
    }
  };

  const handleCreateCourse = async (e) => {
    e.preventDefault();
    if (!newCode.trim() || !newName.trim()) return;
    try {
      await createCourse(newCode.trim().toUpperCase(), newName.trim(), newInstructor.trim(), newSchedule.trim(), newPortal);
      setShowAddModal(false);
      setNewCode("");
      setNewName("");
      setNewInstructor("");
      setNewSchedule("");
      await loadData();
    } catch (err) {
      setError(err.message || "Failed to create course.");
    }
  };

  const handleDeleteCourse = async (courseId) => {
    try {
      await deleteCourse(courseId);
      await loadData();
    } catch (err) {
      setError(err.message || "Failed to remove course.");
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-[#090b10] text-[#E2E8F0]">
      {/* Top Banner / Academic Controls */}
      <div className="flex shrink-0 flex-col gap-3 border-b border-[#1A1F2C] bg-[#0E121B]/90 px-6 py-4 backdrop-blur-md sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold tracking-wide text-white">Academics & Portals</h1>
            <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400">
              Nightly Sync Active (4:00 AM)
            </span>
          </div>
          <p className="mt-0.5 text-xs text-[#8E9EB5]">
            Canvas, FLVS, and LMS homework integration · Seamless auto-authentication
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Homework Mode Toggle */}
          <div className="flex items-center rounded-lg border border-[#23293D] bg-[#131722] p-0.5 text-xs">
            <button
              type="button"
              onClick={() => handleToggleHomeworkMode("solve")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 font-medium transition-all ${
                homeworkMode === "solve"
                  ? "border border-cyan-500/40 bg-cyan-500/20 text-cyan-300 shadow-sm"
                  : "text-[#8E9EB5] hover:text-white"
              }`}
            >
              <span>⚡ Autopilot Solver</span>
            </button>
            <button
              type="button"
              onClick={() => handleToggleHomeworkMode("tutor")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 font-medium transition-all ${
                homeworkMode === "tutor"
                  ? "border border-emerald-500/40 bg-emerald-500/20 text-emerald-300 shadow-sm"
                  : "text-[#8E9EB5] hover:text-white"
              }`}
            >
              <span>🎓 Tutor Mode</span>
            </button>
          </div>

          {/* Sync Button */}
          <button
            type="button"
            onClick={handleSyncPortals}
            disabled={syncing}
            className="flex items-center gap-1.5 rounded-lg border border-[#23293D] bg-[#131722] px-3.5 py-1.5 text-xs font-medium text-[#CBD5E1] transition-all hover:bg-[#1A1F2C] hover:text-white disabled:opacity-50"
          >
            <span className={syncing ? "animate-spin" : ""}>🔄</span>
            <span>{syncing ? "Syncing Portals..." : "Sync Portals"}</span>
          </button>

          {/* Add Course Button */}
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1 rounded-lg bg-emerald-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 transition-all hover:bg-emerald-400"
          >
            <span>+ Add Course</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-6 mt-4 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-2.5 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 space-y-6 p-6">
        {loading ? (
          <div className="flex h-64 items-center justify-center text-xs text-[#8E9EB5]">
            Loading your courses and portal data…
          </div>
        ) : courses.length === 0 ? (
          /* Empty / First-Time State */
          <div className="mx-auto flex max-w-xl flex-col items-center justify-center rounded-2xl border border-[#1E2433] bg-[#0E121B]/60 p-10 text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-500/20 bg-emerald-500/10 text-2xl">
              🎓
            </div>
            <h2 className="text-lg font-bold text-white">No courses connected yet</h2>
            <p className="mt-1.5 max-w-sm text-xs text-[#8E9EB5] leading-relaxed">
              Connect your Canvas LMS, FLVS, or university portal in Settings, or add your classes manually. Nova will automatically detect your syllabus, assignments, and deadlines.
            </p>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => setShowAddModal(true)}
                className="rounded-xl bg-emerald-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-400 transition-all"
              >
                + Add Course Manually
              </button>
              <button
                type="button"
                onClick={() => onOpenChatWithPrompt?.("Nova, how do I connect my Canvas or FLVS portal?")}
                className="rounded-xl border border-[#23293D] bg-[#141824] px-4 py-2 text-xs font-medium text-[#CBD5E1] hover:text-white hover:bg-[#1A2030] transition-all"
              >
                Learn How Portal Sync Works
              </button>
            </div>
          </div>
        ) : (
          /* Courses Grid */
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#8E9EB5] mb-3">
              Enrolled Courses ({courses.length})
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {courses.map((course) => (
                <div
                  key={course.id || course.code}
                  className="group relative flex flex-col justify-between rounded-xl border border-[#1E2433] bg-[#0E121B]/80 p-4 transition-all hover:border-emerald-500/40 hover:bg-[#121622] shadow-sm"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="rounded bg-[#1A2030] px-2 py-0.5 text-xs font-semibold text-emerald-400 border border-emerald-500/20">
                        {course.code}
                      </span>
                      <span className="text-[11px] text-[#8E9EB5]">
                        {course.portal_type || "Canvas LMS"}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-white group-hover:text-emerald-300 transition-colors">
                      {course.name}
                    </h3>
                    {course.instructor && (
                      <p className="mt-1 text-xs text-[#8E9EB5]">
                        Instructor: {course.instructor}
                      </p>
                    )}
                    {course.schedule && (
                      <p className="mt-0.5 text-[11px] text-[#5E6D82]">
                        {course.schedule}
                      </p>
                    )}
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-[#1A1F2C] pt-3">
                    <span className="text-xs text-[#8E9EB5]">
                      {course.assignment_count ? `${course.assignment_count} open assignments` : "Up to date"}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          onOpenChatWithPrompt?.(
                            `Nova open Chrome and solve open homework for ${course.code} (${course.name})`
                          )
                        }
                        className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/20 transition-all"
                      >
                        ⚡ Solve
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteCourse(course.id)}
                        className="text-xs text-[#5E6D82] hover:text-rose-400 p-1"
                        title="Remove course"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Self-Healing Homework Learner Module */}
        <div className="rounded-xl border border-[#1E2433] bg-[#0E121B]/80 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-base">🧠</span>
              <h2 className="text-sm font-semibold text-white">Self-Healing Homework Learner</h2>
            </div>
            <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400 border border-emerald-500/20">
              Active Mastery Engine
            </span>
          </div>
          <p className="text-xs text-[#8E9EB5] leading-relaxed">
            When Nova encounters a novel question type or interactive widget on assignments (e.g. Knewton Alta parabola graphing, ALEKS coordinate sliders, matrix inputs), Nova automatically figures out the coordinates, solves the problem, and saves the mastered recipe so future problems are solved instantly.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 text-xs">
            <div className="rounded-lg border border-[#23293D] bg-[#121622] p-2.5">
              <span className="text-[#8E9EB5] block text-[10px] uppercase font-semibold">Virtual Cursor</span>
              <span className="text-white font-medium mt-0.5 block">Drag & Click Active</span>
            </div>
            <div className="rounded-lg border border-[#23293D] bg-[#121622] p-2.5">
              <span className="text-[#8E9EB5] block text-[10px] uppercase font-semibold">Mastered Widgets</span>
              <span className="text-emerald-400 font-medium mt-0.5 block">12 Interactive Types</span>
            </div>
            <div className="rounded-lg border border-[#23293D] bg-[#121622] p-2.5">
              <span className="text-[#8E9EB5] block text-[10px] uppercase font-semibold">LMS Platforms</span>
              <span className="text-cyan-400 font-medium mt-0.5 block">Canvas, FLVS, Alta</span>
            </div>
            <div className="rounded-lg border border-[#23293D] bg-[#121622] p-2.5">
              <span className="text-[#8E9EB5] block text-[10px] uppercase font-semibold">Self-Healing</span>
              <span className="text-emerald-400 font-medium mt-0.5 block">Auto-Recovery On</span>
            </div>
          </div>
        </div>

        {/* Assignments List if any */}
        {assignments.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#8E9EB5] mb-3">
              Upcoming Homework ({assignments.length})
            </h2>
            <div className="divide-y divide-[#1A1F2C] rounded-xl border border-[#1E2433] bg-[#0E121B]/80 overflow-hidden shadow-sm">
              {assignments.map((item, i) => (
                <div key={i} className="flex items-center justify-between p-3.5 hover:bg-[#121622] transition-colors">
                  <div>
                    <h4 className="text-xs font-semibold text-white">{item.title}</h4>
                    <p className="text-[11px] text-[#8E9EB5] mt-0.5">
                      {item.course_name} · Due: {item.due_at || "Upcoming"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      onOpenChatWithPrompt?.(
                        `Nova open Chrome and solve assignment "${item.title}" for ${item.course_name}`
                      )
                    }
                    className="rounded-md bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 transition-all"
                  >
                    Solve with Autopilot
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Add Course Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-[#23293D] bg-[#0E121B] p-6 shadow-2xl">
            <h3 className="text-sm font-semibold text-white">Add Academic Course</h3>
            <p className="mt-1 text-xs text-[#8E9EB5]">
              Enter the course details to track syllabus, notes, and assignments.
            </p>

            <form onSubmit={handleCreateCourse} className="mt-4 space-y-3">
              <div>
                <label className="block text-[11px] font-semibold text-[#8E9EB5] uppercase">
                  Course Code
                </label>
                <input
                  type="text"
                  placeholder="e.g. CS101, MATH201, BIO100"
                  value={newCode}
                  onChange={(e) => setNewCode(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-[#23293D] bg-[#141824] px-3 py-2 text-xs text-white placeholder-[#5E6D82] focus:border-emerald-500/60 focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-[#8E9EB5] uppercase">
                  Course Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Introduction to Computer Science"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-[#23293D] bg-[#141824] px-3 py-2 text-xs text-white placeholder-[#5E6D82] focus:border-emerald-500/60 focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-[#8E9EB5] uppercase">
                  Instructor (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Dr. Smith"
                  value={newInstructor}
                  onChange={(e) => setNewInstructor(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-[#23293D] bg-[#141824] px-3 py-2 text-xs text-white placeholder-[#5E6D82] focus:border-emerald-500/60 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-[#8E9EB5] uppercase">
                  LMS Portal
                </label>
                <select
                  value={newPortal}
                  onChange={(e) => setNewPortal(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-[#23293D] bg-[#141824] px-3 py-2 text-xs text-white focus:border-emerald-500/60 focus:outline-none"
                >
                  <option value="Canvas LMS">Canvas LMS</option>
                  <option value="FLVS">FLVS</option>
                  <option value="Blackboard">Blackboard</option>
                  <option value="Brightspace">Brightspace</option>
                  <option value="Direct / Manual">Direct / Manual</option>
                </select>
              </div>

              <div className="mt-5 flex items-center justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="rounded-lg border border-[#23293D] bg-[#141824] px-3.5 py-1.5 text-xs font-medium text-[#CBD5E1] hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-emerald-500 px-4 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
                >
                  Save Course
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
