import { useState, useEffect } from "react";
import NovaLogo from "./NovaLogo.jsx";
import SmartSuggestInput from "./school/SmartSuggestInput.jsx";
import {
  getUserProfile,
  updateUserProfile,
  textToSpeech,
  createCourse,
  uploadSyllabus,
  connectObsidianVault,
  getAppSettings,
  updateAppSettings,
  selectDesktopFolder,
  detectObsidianVaults,
} from "../api.js";
import { playTtsAudio } from "../lib/ttsPlayback.js";

const VOICES = [
  { id: "en-US-JennyNeural", name: "Jenny", desc: "Warm, natural & friendly", gender: "Female" },
  { id: "en-US-GuyNeural", name: "Guy", desc: "Crisp, clear & articulate", gender: "Male" },
  { id: "en-US-AriaNeural", name: "Aria", desc: "Expressive & enthusiastic", gender: "Female" },
  { id: "en-US-ChristopherNeural", name: "Christopher", desc: "Deep, calm & thoughtful", gender: "Male" },
];

export default function OnboardingModal({ isOpen, onClose, onComplete }) {
  const searchParams = new URLSearchParams(window.location.search);
  const [step, setStep] = useState(() => Number(searchParams.get("step")) || 1);
  const [name, setName] = useState("");
  const [school, setSchool] = useState("");
  const [major, setMajor] = useState("");
  const [mode, setMode] = useState("autopilot"); // autopilot or socratic
  const [selectedVoice, setSelectedVoice] = useState("en-US-JennyNeural");
  const [previewingVoice, setPreviewingVoice] = useState(null);
  const [speechSanitizer, setSpeechSanitizer] = useState(true);
  
  // Multi-platform support: user can have classes on Canvas AND FLVS
  const [selectedPlatforms, setSelectedPlatforms] = useState(["canvas"]);
  const [selectedHomeworkHubs, setSelectedHomeworkHubs] = useState(["knewton", "connect"]);
  
  const [syllabusFile, setSyllabusFile] = useState(null);
  const [obsidianPath, setObsidianPath] = useState("");
  const [detectedVaults, setDetectedVaults] = useState([]);
  const [showHowTo, setShowHowTo] = useState(true);
  const [activeHowToTab, setActiveHowToTab] = useState("classes");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isOpen) {
      getUserProfile()
        .then((p) => {
          if (p) {
            setName(p.name === "Student" ? "" : p.name);
            setSchool(p.school || "");
            setMajor(p.major || "");
          }
        })
        .catch(() => {});
      getAppSettings()
        .then((s) => {
          if (s?.tts_voice_id) setSelectedVoice(s.tts_voice_id);
        })
        .catch(() => {});
      detectObsidianVaults()
        .then((res) => {
          if (res?.detected && res.vaults?.length > 0) {
            setDetectedVaults(res.vaults);
            const active = res.vaults.find((v) => v.is_open) || res.vaults[0];
            if (active) {
              setObsidianPath(active.path);
            }
          }
        })
        .catch(() => {});
    }
  }, [isOpen]);

  if (!isOpen) return null;

  async function handlePreviewVoice(voiceId, voiceName) {
    if (previewingVoice) return;
    setPreviewingVoice(voiceId);
    try {
      const sampleText = `Hello! I'm ${voiceName}, your autonomous copilot. I'm ready to help you with your coursework.`;
      const audioBlob = await textToSpeech(sampleText, voiceId);
      await playTtsAudio(audioBlob, {
        onStart: () => {},
        onEnd: () => setPreviewingVoice(null),
      });
    } catch {
      setPreviewingVoice(null);
    }
  }

  async function handleBrowseVaultFolder() {
    try {
      const picked = await selectDesktopFolder();
      if (picked) {
        setObsidianPath(picked);
      }
    } catch (e) {
      console.warn("Folder picker cancelled or failed", e);
    }
  }

  function togglePlatform(id) {
    setSelectedPlatforms(prev =>
      prev.includes(id) ? (prev.length > 1 ? prev.filter(p => p !== id) : prev) : [...prev, id]
    );
  }

  function toggleHomeworkHub(id) {
    setSelectedHomeworkHubs(prev =>
      prev.includes(id) ? prev.filter(h => h !== id) : [...prev, id]
    );
  }

  async function handleFinish() {
    setBusy(true);
    setError("");
    try {
      // 1. Save profile
      await updateUserProfile({
        name: name.trim() || "Student",
        school: school.trim(),
        major: major.trim(),
        onboarding_completed: 1,
      });

      // 2. Save voice settings
      await updateAppSettings({
        tts_voice_id: selectedVoice,
        speak_summary_only: true,
      });

      // 3. Connect Obsidian vault if provided
      if (obsidianPath.trim()) {
        await connectObsidianVault("Study Vault", obsidianPath.trim()).catch(() => {});
      }

      onComplete?.();
      onClose();
    } catch (err) {
      setError(err.message || "Failed to save onboarding settings.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
      <div className="relative w-full max-w-xl rounded-2xl border border-charcoal-800 bg-charcoal-950 p-6 shadow-2xl text-charcoal-200 animate-in fade-in zoom-in-95 duration-200">
        {/* Step Progress Header */}
        <div className="flex items-center justify-between pb-4 border-b border-charcoal-800/80">
          <div className="flex items-center gap-2.5">
            <NovaLogo size={24} animate={true} />
            <div>
              <h2 className="text-sm font-semibold text-charcoal-100">Welcome to N.O.V.A.</h2>
              <p className="text-[11px] text-charcoal-400">Student Onboarding & Setup</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4].map((s) => (
              <span
                key={s}
                className={`h-2 rounded-full transition-all duration-300 ${
                  s === step ? "w-6 bg-cyan-400" : s < step ? "w-2 bg-emerald-400" : "w-2 bg-charcoal-700"
                }`}
              />
            ))}
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-300 border border-rose-500/20">
            {error}
          </div>
        )}

        {/* Step 1: Student Profile & Mode */}
        {step === 1 && (
          <div className="space-y-4 py-4 text-[13px]">
            {/* Beginner Quickstart Accordion */}
            <div className="rounded-xl border border-cyan-500/30 bg-gradient-to-br from-cyan-950/30 to-charcoal-900/60 p-3.5 shadow-sm">
              <button
                type="button"
                onClick={() => setShowHowTo(!showHowTo)}
                className="flex w-full items-center justify-between text-left text-xs font-semibold text-cyan-200"
              >
                <div className="flex items-center gap-2">
                  <span className="text-base">🚀</span>
                  <span>Beginner Quickstart: How N.O.V.A. Works</span>
                </div>
                <span className="rounded bg-cyan-500/20 px-2 py-0.5 text-[11px] font-medium text-cyan-300">
                  {showHowTo ? "▲ Close Guide" : "▼ Open Beginner Walkthrough"}
                </span>
              </button>

              {showHowTo && (
                <div className="mt-3.5 space-y-3 pt-3 border-t border-cyan-500/20">
                  {/* Tabs */}
                  <div className="flex flex-wrap gap-1.5 border-b border-charcoal-800 pb-2">
                    {[
                      { id: "classes", label: "🎓 Connecting Classes", title: "1-Click Canvas / FLVS Sync" },
                      { id: "autopilot", label: "⚡ Auto-Pilot vs Tutor", title: "Homework Solving vs Studying" },
                      { id: "gaming", label: "🎮 Background Gaming", title: "Zero Mouse Cursor Hijacking" },
                      { id: "notes", label: "📷 Snap Notes & Obsidian", title: "Handwriting OCR to Notes" },
                      { id: "voice", label: "🎙️ Voice Sphere", title: "Acoustic Sphere & Miniplayer" },
                    ].map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveHowToTab(tab.id)}
                        className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                          activeHowToTab === tab.id
                            ? "bg-cyan-500/20 text-cyan-200 border border-cyan-500/40"
                            : "bg-charcoal-800/80 text-charcoal-400 hover:text-charcoal-200"
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {/* Content per tab */}
                  {activeHowToTab === "classes" && (
                    <div className="rounded-lg bg-charcoal-900/90 p-3 border border-charcoal-800 text-[11.5px] space-y-1.5">
                      <h4 className="font-semibold text-cyan-200">How do my classes connect?</h4>
                      <p className="text-charcoal-300 leading-relaxed">
                        You <strong>never</strong> log in to Knewton Alta, ALEKS, Connect, or Lumen separately! You only log in to your main school portal (<strong>Canvas LMS</strong> or <strong>FLVS</strong>). Nova follows your course links directly into homework assignments. Just click <em>&quot;Analyze My Classes&quot;</em> and Nova extracts your enrolled courses, meeting times, and syllabi automatically.
                      </p>
                    </div>
                  )}

                  {activeHowToTab === "autopilot" && (
                    <div className="rounded-lg bg-charcoal-900/90 p-3 border border-charcoal-800 text-[11.5px] space-y-1.5">
                      <h4 className="font-semibold text-emerald-200">Auto-Pilot Solver vs. Socratic Tutor</h4>
                      <p className="text-charcoal-300 leading-relaxed">
                        • <strong>Auto-Pilot Mode:</strong> Prompt Nova (e.g. <em>&quot;Nova, do all open calculus homework&quot;</em>) and it will autonomously solve and submit each problem one by one, self-healing through errors.<br />
                        • <strong>Socratic Tutor Mode:</strong> When studying for an exam, Nova withholds answers and gives you intuitive hints and step-by-step guidance so you master the material.
                      </p>
                    </div>
                  )}

                  {activeHowToTab === "gaming" && (
                    <div className="rounded-lg bg-charcoal-900/90 p-3 border border-charcoal-800 text-[11.5px] space-y-1.5">
                      <h4 className="font-semibold text-purple-200">Play Games While Homework Solves</h4>
                      <p className="text-charcoal-300 leading-relaxed">
                        In Settings, switch to <strong>Silent Background Mode</strong>. Nova uses isolated browser protocol events—it <strong>never steals or moves your Windows mouse cursor</strong>. You can play Valorant, Steam games, or watch Netflix fullscreen while your homework completes quietly!
                      </p>
                    </div>
                  )}

                  {activeHowToTab === "notes" && (
                    <div className="rounded-lg bg-charcoal-900/90 p-3 border border-charcoal-800 text-[11.5px] space-y-1.5">
                      <h4 className="font-semibold text-amber-200">Snap Photos of Notes into Obsidian</h4>
                      <p className="text-charcoal-300 leading-relaxed">
                        Have handwritten class notes or whiteboard diagrams? Take a photo and paste it into chat. Nova reads handwriting, formats formulas into clean LaTeX, and saves them straight into your local Obsidian vault organized by class.
                      </p>
                    </div>
                  )}

                  {activeHowToTab === "voice" && (
                    <div className="rounded-lg bg-charcoal-900/90 p-3 border border-charcoal-800 text-[11.5px] space-y-1.5">
                      <h4 className="font-semibold text-sky-200">Voice Reactor & Compact Miniplayer</h4>
                      <p className="text-charcoal-300 leading-relaxed">
                        Press <kbd className="px-1 py-0.5 rounded bg-charcoal-800 border border-charcoal-700 text-charcoal-200 font-mono text-[10px]">Alt+Space</kbd> or click the mic button anytime to talk. Watch the optical acoustic sphere react in real time. You can also minimize Nova into a sleek desktop floating sphere miniplayer.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <h3 className="text-sm font-semibold text-charcoal-100">1. Student Profile & Learning Style</h3>
              <p className="text-xs text-charcoal-400 mt-0.5">
                N.O.V.A. personalizes its answers, course scheduling, and research assistant to you. Type your school or major acronym and Nova will suggest matches.
              </p>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-charcoal-300 mb-1">Your Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Alex"
                  className="w-full rounded-lg bg-charcoal-900 border border-charcoal-800 px-3 py-2 text-charcoal-100 placeholder:text-charcoal-600 focus:border-cyan-500/60 focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-charcoal-300 mb-1">School / College / Institution</label>
                  <SmartSuggestInput
                    type="school"
                    value={school}
                    onChange={setSchool}
                    placeholder="Type e.g. tsc, fsu, flvs..."
                    className="w-full rounded-lg bg-charcoal-900 border border-charcoal-800 px-3 py-2 text-charcoal-100 placeholder:text-charcoal-600 focus:border-cyan-500/60 focus:outline-none"
                  />
                  <p className="text-[10px] text-charcoal-500 mt-1">Smart match: type &quot;tsc&quot; for Tallahassee State College</p>
                </div>
                <div>
                  <label className="block text-xs font-medium text-charcoal-300 mb-1">Major or Field of Study</label>
                  <SmartSuggestInput
                    type="major"
                    value={major}
                    onChange={setMajor}
                    placeholder="Type e.g. cs, econ, math..."
                    className="w-full rounded-lg bg-charcoal-900 border border-charcoal-800 px-3 py-2 text-charcoal-100 placeholder:text-charcoal-600 focus:border-cyan-500/60 focus:outline-none"
                  />
                  <p className="text-[10px] text-charcoal-500 mt-1">Smart match: type &quot;cs&quot; for Computer Science</p>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-charcoal-300 mb-1.5">
                  Default Problem-Solving Mode
                </label>
                <div className="grid grid-cols-2 gap-2.5">
                  <div
                    onClick={() => setMode("autopilot")}
                    className={`cursor-pointer rounded-xl p-3 border transition-all ${
                      mode === "autopilot"
                        ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-200"
                        : "border-charcoal-800 bg-charcoal-900/60 hover:bg-charcoal-800/40"
                    }`}
                  >
                    <div className="font-semibold text-xs flex items-center gap-1.5">
                      <span>⚡ Auto-Pilot / Direct Solver</span>
                    </div>
                    <p className="text-[11px] text-charcoal-400 mt-1 leading-snug">
                      Instant SymPy calculations, formulas, and auto-submit solution steps on homework portals.
                    </p>
                  </div>
                  <div
                    onClick={() => setMode("socratic")}
                    className={`cursor-pointer rounded-xl p-3 border transition-all ${
                      mode === "socratic"
                        ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200"
                        : "border-charcoal-800 bg-charcoal-900/60 hover:bg-charcoal-800/40"
                    }`}
                  >
                    <div className="font-semibold text-xs flex items-center gap-1.5">
                      <span>🎓 Socratic Tutor Mode</span>
                    </div>
                    <p className="text-[11px] text-charcoal-400 mt-1 leading-snug">
                      Withholds direct answers; guides you step-by-step with intuitive hints so you master concepts.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Course Platforms & Homework Hubs */}
        {step === 2 && (
          <div className="space-y-4 py-4 text-[13px]">
            <div>
              <h3 className="text-sm font-semibold text-charcoal-100">2. Class Platforms & Homework Portals</h3>
              <p className="text-xs text-charcoal-400 mt-0.5">
                Students often take classes across multiple systems (e.g. Canvas + FLVS) and do assignments on specialized homework tools (e.g. Knewton Alta). Select all that apply:
              </p>
            </div>

            <div className="space-y-3.5">
              {/* Enrolled Class Platforms */}
              <div>
                <label className="block text-xs font-medium text-charcoal-300 mb-1.5">
                  1. Enrolled Class Platforms (Where you take classes)
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: "canvas", name: "Canvas LMS", desc: "Instructure Canvas (e.g. TSC, FSU, UF)" },
                    { id: "flvs", name: "Florida Virtual School (FLVS)", desc: "FLVS Flex / Full Time" },
                    { id: "blackboard", name: "Blackboard Learn", desc: "Anthology Learn portal" },
                    { id: "brightspace", name: "Brightspace (D2L)", desc: "Desire2Learn Courseware" },
                  ].map((p) => {
                    const active = selectedPlatforms.includes(p.id);
                    return (
                      <div
                        key={p.id}
                        onClick={() => togglePlatform(p.id)}
                        className={`cursor-pointer rounded-xl p-3 border transition-all ${
                          active
                            ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-200"
                            : "border-charcoal-800 bg-charcoal-900 hover:bg-charcoal-800/60 text-charcoal-300"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-xs">{p.name}</span>
                          <span className={`text-xs ${active ? "text-cyan-400" : "text-charcoal-600"}`}>
                            {active ? "✓ Selected" : "+ Add"}
                          </span>
                        </div>
                        <div className="text-[11px] text-charcoal-400 mt-1">{p.desc}</div>
                        {active && (
                          <div className="mt-2 pt-2 border-t border-cyan-500/20 flex items-center justify-between text-[11px]">
                            <span className="text-emerald-400 flex items-center gap-1">
                              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                              Ready for Sign-In
                            </span>
                            <span className="text-cyan-300 font-medium">Auto-Syncs</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Homework & Assignment Portals */}
              <div>
                <label className="block text-xs font-medium text-charcoal-300 mb-1.5">
                  2. Homework & Problem-Solving Portals (Where assignments are completed)
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { id: "knewton", name: "Knewton Alta", desc: "Adaptive Math & Calc" },
                    { id: "connect", name: "McGraw-Hill Connect", desc: "SmartBook & Econ" },
                    { id: "pearson", name: "Pearson MyLab", desc: "MyLab Math / Science" },
                  ].map((h) => {
                    const active = selectedHomeworkHubs.includes(h.id);
                    return (
                      <div
                        key={h.id}
                        onClick={() => toggleHomeworkHub(h.id)}
                        className={`cursor-pointer rounded-lg p-2.5 border text-center transition-all ${
                          active
                            ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
                            : "border-charcoal-800 bg-charcoal-900 hover:bg-charcoal-800/60 text-charcoal-400"
                        }`}
                      >
                        <div className="font-semibold text-xs">{h.name}</div>
                        <div className="text-[10px] text-charcoal-400 mt-0.5">{h.desc}</div>
                        <div className="mt-1 text-[10px] font-medium text-emerald-400">
                          {active ? "✓ Active Solver" : "+ Enable"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Autonomous Course Discovery Info */}
              <div className="rounded-xl bg-charcoal-900/60 p-3 border border-charcoal-800 text-[11.5px] space-y-1.5">
                <div className="flex items-center gap-2 text-cyan-300 font-semibold text-xs">
                  <span>✨ Autonomous Course Discovery</span>
                </div>
                <p className="text-charcoal-400 text-[11px] leading-relaxed">
                  No manual typing needed! When you sign into Canvas or FLVS, N.O.V.A. automatically crawls your enrolled courses, meeting days, semester schedules, professor details, and syllabi into your local database.
                </p>
              </div>

              <div className="rounded-lg bg-amber-500/10 p-2.5 border border-amber-500/20 text-[11.5px] text-amber-300 flex items-start gap-2">
                <span className="text-sm">🛡️</span>
                <span>
                  <strong>Proctoring Protection Active:</strong> N.O.V.A. automatically halts all browser automation if Honorlock, LockDown Browser, Proctorio, or Examity are detected.
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Neural Voice Engine */}
        {step === 3 && (
          <div className="space-y-4 py-4 text-[13px]">
            <div>
              <h3 className="text-sm font-semibold text-charcoal-100">3. Neural Voice & Speech Sanitizer</h3>
              <p className="text-xs text-charcoal-400 mt-0.5">
                Sub-second neural voice synthesis. Hear real previews below and select your preferred voice:
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2.5">
              {VOICES.map((v) => (
                <div
                  key={v.id}
                  onClick={() => setSelectedVoice(v.id)}
                  className={`cursor-pointer rounded-xl p-3 border transition-all relative ${
                    selectedVoice === v.id
                      ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-500/30"
                      : "border-charcoal-800 bg-charcoal-900 hover:bg-charcoal-800/60"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-xs text-charcoal-100 flex items-center gap-1.5">
                      <span className={`h-2 w-2 rounded-full ${selectedVoice === v.id ? "bg-cyan-400" : "bg-charcoal-600"}`} />
                      {v.name}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePreviewVoice(v.id, v.name);
                      }}
                      className="rounded bg-charcoal-800 hover:bg-charcoal-700 px-2 py-0.5 text-[11px] text-cyan-400 transition-colors border border-charcoal-700"
                    >
                      {previewingVoice === v.id ? "Playing…" : "▶ Preview"}
                    </button>
                  </div>
                  <div className="text-[11px] text-charcoal-400 mt-1.5">{v.desc}</div>
                </div>
              ))}
            </div>

            <div className="rounded-xl bg-charcoal-900/60 p-3.5 border border-charcoal-800 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-semibold text-charcoal-200">Smart Speech Sanitizer</span>
                  <p className="text-[11px] text-charcoal-400">
                    Never reads raw code blocks, stack traces, or markdown noise aloud.
                  </p>
                </div>
                <input
                  type="checkbox"
                  checked={speechSanitizer}
                  onChange={(e) => setSpeechSanitizer(e.target.checked)}
                  className="h-4 w-4 accent-cyan-500 rounded"
                />
              </div>
              <p className="text-[11px] text-emerald-400 font-mono bg-charcoal-950 p-2 rounded border border-charcoal-800">
                Formula \( f&apos;(x) \) is pronounced as &quot;f prime of x&quot;. Code blocks are quietly routed to the Studio editor.
              </p>
            </div>
          </div>
        )}

        {/* Step 4: Notes & Obsidian Ecosystem */}
        {step === 4 && (
          <div className="space-y-4 py-4 text-[13px]">
            <div>
              <h3 className="text-sm font-semibold text-charcoal-100">4. Unified Notes & Obsidian Integration</h3>
              <p className="text-xs text-charcoal-400 mt-0.5">
                N.O.V.A. automatically syncs lecture summaries, formulas, and homework solutions directly to your local notes.
              </p>
            </div>

            <div className="space-y-3.5">
              {/* Auto-detected Vaults */}
              {detectedVaults.length > 0 && (
                <div className="rounded-xl bg-purple-500/10 border border-purple-500/25 p-3.5 space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold text-purple-300">
                    <span className="flex items-center gap-1.5">
                      <span>⚡ Detected Obsidian Vaults on your computer:</span>
                    </span>
                    <span className="text-[10px] text-purple-400 font-mono">1-Click Connect</span>
                  </div>
                  <div className="space-y-1.5">
                    {detectedVaults.map((v) => {
                      const isSelected = obsidianPath === v.path;
                      return (
                        <div
                          key={v.id}
                          onClick={() => setObsidianPath(v.path)}
                          className={`flex items-center justify-between p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                            isSelected
                              ? "bg-purple-500/20 border-purple-500/60 text-purple-100 ring-1 ring-purple-500/40"
                              : "bg-charcoal-900 border-charcoal-800 text-charcoal-300 hover:bg-charcoal-800/80"
                          }`}
                        >
                          <div className="min-w-0 pr-3">
                            <span className="font-semibold block truncate text-charcoal-100">
                              📁 {v.name} {v.is_open ? <span className="ml-1.5 text-[10px] font-normal text-emerald-400">· Open in Obsidian</span> : ""}
                            </span>
                            <span className="text-[10.5px] font-mono text-charcoal-400 block truncate">{v.path}</span>
                          </div>
                          <button
                            type="button"
                            className={`shrink-0 px-3 py-1 rounded text-xs font-medium transition-colors ${
                              isSelected
                                ? "bg-purple-600 text-white font-semibold shadow-sm"
                                : "bg-charcoal-800 text-purple-300 hover:bg-charcoal-700"
                            }`}
                          >
                            {isSelected ? "✓ Connected" : "Connect"}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-charcoal-300 mb-1.5">
                  Vault Folder Path
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={obsidianPath}
                    onChange={(e) => setObsidianPath(e.target.value)}
                    placeholder="e.g. Documents\Obsidian\College"
                    className="flex-1 rounded-lg bg-charcoal-900 border border-charcoal-800 px-3 py-2 text-charcoal-100 placeholder:text-charcoal-600 focus:border-cyan-500/60 focus:outline-none font-mono text-xs"
                  />
                  <button
                    type="button"
                    onClick={handleBrowseVaultFolder}
                    className="shrink-0 px-3 py-2 rounded-lg bg-charcoal-800 hover:bg-charcoal-700 text-xs font-medium text-white border border-charcoal-700 transition-colors flex items-center gap-1.5"
                  >
                    <span>📂 Browse Folder...</span>
                  </button>
                </div>
                <p className="text-[11px] text-charcoal-400 mt-1.5">
                  Click &quot;Browse Folder...&quot; to pick your existing vault directory from Windows File Explorer.
                </p>
              </div>

              {/* Obsidian download info */}
              <div className="rounded-xl bg-charcoal-900/60 p-3 border border-charcoal-800 flex items-start gap-3">
                <span className="text-lg">🔮</span>
                <div>
                  <h4 className="text-xs font-semibold text-charcoal-200">Don&apos;t have Obsidian yet?</h4>
                  <p className="text-[11px] text-charcoal-400 mt-0.5 leading-relaxed">
                    Obsidian is a free, 100% private Markdown knowledge base with mind-maps, canvas graphs, and offline backup. Download free at{" "}
                    <a
                      href="https://obsidian.md"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan-400 hover:underline font-medium"
                    >
                      obsidian.md
                    </a>. You can always connect or change your vault folder later in Settings.
                  </p>
                </div>
              </div>

              <div className="rounded-xl bg-charcoal-900/60 p-3.5 border border-charcoal-800 space-y-2.5">
                <span className="text-xs font-semibold text-charcoal-200">How to use other note apps with N.O.V.A.:</span>
                
                <div className="flex items-start gap-2 text-[12px]">
                  <span className="text-cyan-400">📱</span>
                  <div>
                    <strong className="text-charcoal-200">Apple Notes / GoodNotes / Notability:</strong>
                    <p className="text-charcoal-400 text-[11px]">
                      Export any note page or PDF summary, then drag & drop directly into Nova or copy & paste.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-2 text-[12px]">
                  <span className="text-emerald-400">📝</span>
                  <div>
                    <strong className="text-charcoal-200">Handwritten Paper & Whiteboards:</strong>
                    <p className="text-charcoal-400 text-[11px]">
                      Take a photo with your phone or camera and press <kbd className="bg-charcoal-800 px-1 py-0.5 rounded text-charcoal-300 font-mono text-[10px]">Ctrl+V</kbd> in chat. Nova&apos;s multimodal vision engine transcribes handwriting, diagrams, and math formulas automatically!
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Modal Footer Controls */}
        <div className="flex items-center justify-between pt-4 border-t border-charcoal-800/80 mt-2">
          {step > 1 ? (
            <button
              onClick={() => setStep(step - 1)}
              className="rounded-lg bg-charcoal-800 px-3.5 py-1.5 text-xs font-medium text-charcoal-300 hover:bg-charcoal-700 transition-colors"
            >
              Back
            </button>
          ) : (
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-xs text-charcoal-500 hover:text-charcoal-300 transition-colors"
            >
              Skip Setup
            </button>
          )}

          {step < 4 ? (
            <button
              onClick={() => setStep(step + 1)}
              className="rounded-lg bg-cyan-600 hover:bg-cyan-500 px-4 py-1.5 text-xs font-semibold text-white transition-colors ml-auto shadow-sm"
            >
              Continue
            </button>
          ) : (
            <button
              onClick={handleFinish}
              disabled={busy}
              className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-5 py-1.5 text-xs font-semibold text-white transition-colors ml-auto shadow-sm disabled:opacity-50"
            >
              {busy ? "Saving Setup…" : "✦ Complete & Launch N.O.V.A."}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
