import { useEffect, useState } from "react";
import {
  listCourses,
  listObsidianVaults,
  connectObsidianVault,
  disconnectObsidianVault,
  getCanvasStatus,
  saveCanvasCredentials,
  saveCanvasFeed,
  detectObsidianVaults,
  selectDesktopFolder,
} from "../../api.js";

export default function AcademicsPanel() {
  const [courses, setCourses] = useState([]);
  const [vaults, setVaults] = useState([]);
  const [detectedVaults, setDetectedVaults] = useState([]);
  const [vaultName, setVaultName] = useState("");
  const [vaultPath, setVaultPath] = useState("");
  const [canvasStatus, setCanvasStatus] = useState(null);
  const [canvasUrl, setCanvasUrl] = useState("");
  const [canvasToken, setCanvasToken] = useState("");
  const [canvasFeed, setCanvasFeed] = useState("");
  const [canvasMethod, setCanvasMethod] = useState("token");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    try {
      const [crs, vts, cvs, det] = await Promise.all([
        listCourses().catch(() => []),
        listObsidianVaults().catch(() => []),
        getCanvasStatus().catch(() => null),
        detectObsidianVaults().catch(() => null),
      ]);
      setCourses(crs || []);
      setVaults(vts || []);
      setCanvasStatus(cvs);
      if (det?.detected) setDetectedVaults(det.vaults || []);
      if (cvs?.url) setCanvasUrl(cvs.url);
    } catch {
      // ignore
    }
  }

  async function handleBrowseFolder() {
    try {
      const picked = await selectDesktopFolder();
      if (picked) {
        setVaultPath(picked);
        if (!vaultName) {
          const parts = picked.split(/[\\/]/).filter(Boolean);
          setVaultName(parts[parts.length - 1] || "Study Vault");
        }
      }
    } catch (e) {
      console.warn("Folder picker error", e);
    }
  }

  async function handleConnectVault(e) {
    e.preventDefault();
    if (!vaultPath.trim()) return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      await connectObsidianVault(vaultName.trim() || "My Study Vault", vaultPath.trim());
      setVaultName("");
      setVaultPath("");
      setNote("Obsidian vault connected successfully.");
      await refresh();
    } catch (err) {
      setError(err.message || "Could not connect Obsidian vault.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnectVault(id) {
    if (!window.confirm("Disconnect this Obsidian vault?")) return;
    try {
      await disconnectObsidianVault(id);
      await refresh();
    } catch (err) {
      setError(err.message || "Failed to disconnect vault.");
    }
  }

  async function handleSaveCanvas() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      if (canvasMethod === "token") {
        await saveCanvasCredentials(canvasUrl.trim(), canvasToken.trim());
      } else {
        await saveCanvasFeed(canvasFeed.trim());
      }
      setNote("Canvas credentials saved.");
      await refresh();
    } catch (err) {
      setError(err.message || "Failed to save Canvas configuration.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 text-[13px] text-charcoal-300">
      <div>
        <h3 className="text-sm font-semibold text-charcoal-100">Universal Academic Hub</h3>
        <p className="mt-1 leading-relaxed text-charcoal-400">
          Manage integrations for Florida Virtual School (FLVS.net), Canvas LMS, syllabi parsers, and Obsidian note syncing.
        </p>
      </div>

      {note && (
        <div className="rounded-lg bg-emerald-500/10 px-3.5 py-2 text-emerald-300 border border-emerald-500/20">
          {note}
        </div>
      )}
      {error && (
        <div className="rounded-lg bg-rose-500/10 px-3.5 py-2 text-rose-300 border border-rose-500/20">
          {error}
        </div>
      )}

      {/* Proctoring Shield Status */}
      <div className="rounded-xl bg-charcoal-900/60 p-4 border border-charcoal-800/80 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-base">🛡️</span>
            <span className="font-semibold text-charcoal-200 text-xs uppercase tracking-wider">
              Academic Proctoring Shield
            </span>
          </div>
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400 border border-emerald-500/20">
            Active Guard
          </span>
        </div>
        <p className="text-xs text-charcoal-400 leading-relaxed">
          N.O.V.A. protects your academic integrity by automatically halting all Onyx browser control whenever
          proctored exam sessions are detected (Honorlock, LockDown Browser, Respondus, Proctorio, Examity).
        </p>
      </div>

      {/* Universal Course Portals */}
      <div className="rounded-xl bg-charcoal-900/60 p-4 border border-charcoal-800/80 space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="font-semibold text-xs uppercase tracking-wider text-charcoal-300">
            Supported Class Platforms
          </h4>
          <span className="text-[11px] text-blue-400 font-mono">Universal Support</span>
        </div>
        <p className="text-xs text-charcoal-400 leading-relaxed">
          N.O.V.A. automatically syncs and navigates assignments across Canvas LMS, Blackboard Learn, Brightspace (D2L), Moodle, Knewton Alta, McGraw-Hill Connect, and FLVS.
        </p>
      </div>

      {/* Obsidian Vault Sync */}
      <div className="rounded-xl bg-charcoal-900/60 p-4 border border-charcoal-800/80 space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="font-semibold text-xs uppercase tracking-wider text-charcoal-300">
            Obsidian Vault Integration
          </h4>
          <span className="text-[11px] text-purple-400 font-mono">Bi-Directional Sync</span>
        </div>
        <p className="text-xs text-charcoal-400 leading-relaxed">
          Sync your course notes, homework solutions, and study guides directly to your local Obsidian markdown vault.
        </p>

        {vaults.length > 0 && (
          <div className="space-y-2">
            {vaults.map((v) => (
              <div
                key={v.id}
                className="flex items-center justify-between rounded-lg bg-charcoal-950 p-2.5 border border-charcoal-800"
              >
                <div>
                  <div className="text-xs font-semibold text-charcoal-200">{v.name}</div>
                  <div className="text-[11px] font-mono text-charcoal-500 truncate max-w-sm">{v.path}</div>
                </div>
                <button
                  onClick={() => handleDisconnectVault(v.id)}
                  className="rounded px-2 py-1 text-[11px] text-rose-400 hover:bg-rose-500/10 transition-colors"
                >
                  Disconnect
                </button>
              </div>
            ))}
          </div>
        )}

        {detectedVaults.length > 0 && (
          <div className="rounded-xl bg-purple-500/10 border border-purple-500/25 p-3 space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-purple-300">
              <span>⚡ Auto-Detected Obsidian Vaults on this PC:</span>
              <span className="text-[10px] text-purple-400 font-mono">1-Click Connect</span>
            </div>
            <div className="space-y-1.5">
              {detectedVaults.map((v) => {
                const alreadyConnected = vaults.some((ex) => ex.path === v.path);
                return (
                  <div
                    key={v.id}
                    className="flex items-center justify-between p-2 rounded-lg bg-charcoal-950 border border-charcoal-800 text-xs"
                  >
                    <div className="min-w-0 pr-2">
                      <div className="font-semibold text-charcoal-200 flex items-center gap-1.5">
                        <span>📁 {v.name}</span>
                        {v.is_open && <span className="text-[10px] text-emerald-400 font-normal">· Active Vault</span>}
                      </div>
                      <div className="text-[10.5px] font-mono text-charcoal-500 truncate">{v.path}</div>
                    </div>
                    {alreadyConnected ? (
                      <span className="shrink-0 text-[11px] text-emerald-400 font-medium px-2 py-0.5">
                        ✓ Connected
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={async () => {
                          setBusy(true);
                          try {
                            await connectObsidianVault(v.name, v.path);
                            await refresh();
                          } catch (err) {
                            setError(err.message || "Failed to connect vault.");
                          } finally {
                            setBusy(false);
                          }
                        }}
                        disabled={busy}
                        className="shrink-0 rounded bg-purple-600 hover:bg-purple-500 px-2.5 py-1 text-xs font-medium text-white transition-colors"
                      >
                        Connect
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <form onSubmit={handleConnectVault} className="space-y-2 pt-2 border-t border-charcoal-800/80">
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              value={vaultName}
              onChange={(e) => setVaultName(e.target.value)}
              placeholder="Vault Name (e.g. College Notes)"
              className="rounded-md bg-charcoal-900 border border-charcoal-700/60 px-2.5 py-1.5 text-xs text-charcoal-100 placeholder:text-charcoal-600 focus:outline-none focus:border-cyan-500"
            />
            <div className="flex gap-1.5">
              <input
                type="text"
                value={vaultPath}
                onChange={(e) => setVaultPath(e.target.value)}
                placeholder="Full path or click Browse..."
                className="flex-1 rounded-md bg-charcoal-900 border border-charcoal-700/60 px-2.5 py-1.5 text-xs text-charcoal-100 placeholder:text-charcoal-600 focus:outline-none focus:border-cyan-500"
              />
              <button
                type="button"
                onClick={handleBrowseFolder}
                className="shrink-0 rounded-md bg-charcoal-800 hover:bg-charcoal-700 px-2.5 py-1.5 text-xs text-charcoal-200 border border-charcoal-700/60 transition-colors"
                title="Browse Windows folder"
              >
                📂 Browse
              </button>
            </div>
          </div>
          <button
            type="submit"
            disabled={busy || !vaultPath.trim()}
            className="rounded-md bg-charcoal-800 hover:bg-charcoal-700 px-3 py-1.5 text-xs font-medium text-charcoal-200 border border-charcoal-700/60 transition-colors disabled:opacity-50"
          >
            + Connect Vault
          </button>
        </form>
      </div>

      {/* Canvas LMS Setup */}
      <div className="rounded-xl bg-charcoal-900/60 p-4 border border-charcoal-800/80 space-y-3">
        <h4 className="font-semibold text-xs uppercase tracking-wider text-charcoal-300">
          Canvas LMS Integration
        </h4>
        <div className="flex gap-2">
          {["token", "feed"].map((m) => (
            <button
              key={m}
              onClick={() => setCanvasMethod(m)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                canvasMethod === m
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                  : "bg-charcoal-800 text-charcoal-400 hover:text-charcoal-200"
              }`}
            >
              {m === "token" ? "Access Token" : "Calendar Feed URL"}
            </button>
          ))}
        </div>

        {canvasMethod === "token" ? (
          <div className="space-y-2">
            <div>
              <label className="block text-[11px] text-charcoal-400 mb-1">Canvas Domain URL</label>
              <input
                type="text"
                value={canvasUrl}
                onChange={(e) => setCanvasUrl(e.target.value)}
                placeholder="yourschool.instructure.com"
                className="w-full rounded-md bg-charcoal-900 border border-charcoal-700/60 px-2.5 py-1.5 text-xs text-charcoal-100 placeholder:text-charcoal-600 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-[11px] text-charcoal-400 mb-1">Personal Access Token</label>
              <input
                type="password"
                value={canvasToken}
                onChange={(e) => setCanvasToken(e.target.value)}
                placeholder="Paste Canvas access token"
                className="w-full rounded-md bg-charcoal-900 border border-charcoal-700/60 px-2.5 py-1.5 text-xs text-charcoal-100 placeholder:text-charcoal-600 focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>
        ) : (
          <div>
            <label className="block text-[11px] text-charcoal-400 mb-1">Canvas iCal Feed URL</label>
            <input
              type="text"
              value={canvasFeed}
              onChange={(e) => setCanvasFeed(e.target.value)}
              placeholder="https://yourschool.instructure.com/feeds/calendars/user_...ics"
              className="w-full rounded-md bg-charcoal-900 border border-charcoal-700/60 px-2.5 py-1.5 text-xs text-charcoal-100 placeholder:text-charcoal-600 focus:outline-none focus:border-cyan-500"
            />
          </div>
        )}

        <button
          onClick={handleSaveCanvas}
          disabled={busy}
          className="rounded-md bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-white transition-colors disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save Canvas Connection"}
        </button>
      </div>

      {/* Active Courses */}
      <div className="rounded-xl bg-charcoal-900/60 p-4 border border-charcoal-800/80 space-y-2">
        <h4 className="font-semibold text-xs uppercase tracking-wider text-charcoal-300">
          Enrolled Courses ({courses.length})
        </h4>
        {courses.length === 0 ? (
          <p className="text-xs text-charcoal-500">
            No courses enrolled yet. Upload a course syllabus PDF in the Courses tab to populate your schedule.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 pt-1">
            {courses.map((c) => (
              <div
                key={c.id}
                className="rounded-lg bg-charcoal-950 p-2.5 border border-charcoal-800 text-xs flex items-center justify-between"
              >
                <div>
                  <span className="font-semibold text-charcoal-200">{c.code || c.name}</span>
                  <p className="text-[11px] text-charcoal-500">{c.name}</p>
                </div>
                <span className="rounded bg-charcoal-800 px-1.5 py-0.5 text-[10px] text-charcoal-400 uppercase font-mono">
                  {c.portal || "syllabus"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
