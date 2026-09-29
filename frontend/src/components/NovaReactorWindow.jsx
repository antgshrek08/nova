import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createConversation, getAppSettings, listAssignments, streamChat, textToSpeech, transcribeAudio } from "../api.js";
import { getAudioLevels, playTtsAudio, primeAudioContext, stopTtsAudio } from "../lib/ttsPlayback.js";
import { openMicrophone } from "../lib/microphone.js";
import { attachMicAnalyser, detachMicAnalyser, getMicLevels } from "../lib/micLevels.js";
import { startWakeWordDetection, stopWakeWordDetection } from "../lib/wakeword.js";
import { connectAgentSocket } from "../lib/agentSocket.js";
import ReactorCore from "./chat/ReactorCore.jsx";
import Reactor from "../paper/Reactor.jsx";
import usePrefs from "../paper/usePrefs.js";
import "../paper/mini.css";
import NovaLogo from "./NovaLogo.jsx";

// ChatGPT's Pets shows four agent states and, when several have activity at
// once, prioritises them needs-input -> blocked -> ready -> running. Copied
// verbatim because the ordering is right: "needs you" is the only state where
// the work is stopped until the user moves, and "working" is the only one that
// resolves itself, so it ranks last.
const AGENT_STATUS = {
  needs_input: { label: "Needs you", badge: "!", color: "#fbbf24", ring: "rgba(251,191,36,0.30)" },
  blocked: { label: "Blocked", badge: "!", color: "#fb7185", ring: "rgba(251,113,133,0.30)" },
  ready: { label: "Ready", badge: "✓", color: "#34d399", ring: "rgba(52,211,153,0.30)" },
  working: { label: "Working…", badge: "", color: "#f59e0b", ring: "rgba(245,158,11,0.28)" },
};

export default function NovaReactorWindow({ headless = false, onConversationCompleted }) {
  const [state, setState] = useState("idle");
  const prefs = usePrefs();
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState("");
  const [wake, setWake] = useState(true);
  const [wakeReady, setWakeReady] = useState(false);
  // Agent activity happening elsewhere in Nova. Separate from `state`, which
  // is only ever about this window's own voice turn.
  const [agentActive, setAgentActive] = useState(false);
  const [approvals, setApprovals] = useState(0);
  const [unreadDone, setUnreadDone] = useState(0);
  const [unreadFailed, setUnreadFailed] = useState(0);
  // Quick Chat: the pencil swaps the mic button for a typing box.
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState("");
  const [hovered, setHovered] = useState(false);
  // How many screens there are to cycle through, and which one the pet is on.
  // Only meaningful in the Electron window; in a browser it stays 1 and the
  // monitor button never renders.
  const [displays, setDisplays] = useState({ count: 1, index: 0 });
  const [pinned, setPinned] = useState(true);
  const cardRef = useRef(null);
  const [upcomingAssignment, setUpcomingAssignment] = useState(null);

  useEffect(() => {
    if (headless) return;
    listAssignments().then((items) => {
      if (items && items.length > 0) {
        const pending = items.filter(a => !a.submitted && a.due_at);
        if (pending.length > 0) {
          pending.sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
          setUpcomingAssignment(pending[0]);
        }
      }
    }).catch(() => {});
  }, [headless]);

  function togglePin() {
    const next = !pinned;
    setPinned(next);
    window.electronAPI?.setMiniplayerPinned?.(next);
  }

  useEffect(() => {
    window.electronAPI?.getMiniplayerPinned?.().then((p) => setPinned(p !== false)).catch(() => {});
  }, []);

  // The window is transparent and click-through except where the card is;
  // the main process polls the cursor against the rectangle reported here.
  useEffect(() => {
    const el = cardRef.current;
    const report = window.electronAPI?.setMiniplayerHitRects;
    if (!el || !report) return undefined;
    const send = () => {
      const r = el.getBoundingClientRect();
      report([{ x: r.left, y: r.top, w: r.width, h: r.height }]);
    };
    send();
    const ro = new ResizeObserver(send);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const runtime = useRef({ epoch: 0, recorder: null, stream: null, controller: null, conversation: null, timer: null });
  const activeJobs = useRef(new Set());
  const toggleRef = useRef(null);
  const settings = useRef({ tts_voice_id: "default" });

  function stop() {
    const r = runtime.current;
    r.epoch++;
    r.controller?.abort();
    clearInterval(r.timer);
    if (r.recorder?.state === "recording") { r.recorder.onstop = null; r.recorder.stop(); }
    r.stream?.getTracks().forEach(t => t.stop());
    r.recorder = null;
    r.stream = null;
    detachMicAnalyser();
    stopTtsAudio();
    setState("idle");
  }

  /** Everything after "we have a question": ask Nova, then speak the answer.
   *
   * Split out of the recorder's onstop so Quick Chat's typed input goes down
   * exactly this path. A typed question should behave like a spoken one --
   * same conversation, same spoken reply -- and the surest way to guarantee
   * that is for there to be one implementation rather than two that drift.
   */
  async function answer(text, controller, active) {
    const r = runtime.current;
    setTranscript(text);
    if (!r.conversation) r.conversation = (await createConversation({ tab: "chat", title: "Nova voice" })).id;
    if (!active()) return;
    let reply = "";
    await streamChat(r.conversation, text, event => {
      if (!active()) return;
      if (event.type === "error") throw new Error(event.message || event.content || "Nova could not answer");
      if (event.type === "token") reply += event.content;
    }, { signal: controller.signal });
    if (!active()) return;
    if (!reply.trim()) throw new Error("No answer received. Try again.");
    onConversationCompleted?.(r.conversation);
    settings.current = await getAppSettings();
    if (!active()) return;
    if (settings.current.voice_replies === false) { setState("idle"); return; }
    // Keep the voice surface quick; the complete answer remains in History.
    const spoken = reply.replace(/\x60{3}[\s\S]*?\x60{3}/g, " Code is available in Nova. ").replace(/[*#_]/g, "").trim();
    const brief = settings.current.speak_summary_only && spoken.length > 500 ? spoken.slice(0, 500).replace(/\s+\S*$/, "") + ". The full answer is in Nova." : spoken;
    const audio = await textToSpeech(brief, settings.current.tts_voice_id, controller.signal);
    if (!active()) return;
    await playTtsAudio(audio, { onStart: () => active() && setState("speaking"), onEnd: () => active() && setState("idle") });
  }

  /** Quick Chat's typed half -- same preamble as toggleMic (cancel whatever is
   * running, stand the wake listener down, take a fresh epoch), then straight
   * to the shared answer path without a recording step. */
  async function ask(text) {
    const r = runtime.current;
    stop();
    await stopWakeWordDetection();
    setWakeReady(false);
    const epoch = r.epoch;
    const active = () => epoch === r.epoch;
    const controller = new AbortController();
    r.controller = controller;
    setError("");
    setState("thinking");
    try {
      await answer(text, controller, active);
    } catch (caught) {
      if (active()) { if (caught.name !== "AbortError") setError(caught.message); setState("idle"); }
    }
  }

  async function toggleMic() {
    const r = runtime.current;
    if (r.recorder?.state === "recording") { r.recorder.stop(); return; }
    stop();
    await stopWakeWordDetection();
    setWakeReady(false);
    const epoch = r.epoch;
    const active = () => epoch === r.epoch;
    const controller = new AbortController();
    r.controller = controller;
    setError("");
    setState("listening");
    primeAudioContext();
    try {
      const stream = await openMicrophone();
      if (!active()) { stream.getTracks().forEach(t => t.stop()); return; }
      r.stream = stream;
      attachMicAnalyser(stream);
      const recorder = new MediaRecorder(stream);
      r.recorder = recorder;
      const chunks = [];
      recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = async () => {
        clearInterval(r.timer);
        stream.getTracks().forEach(t => t.stop());
        detachMicAnalyser();
        r.recorder = null;
        r.stream = null;
        if (!active()) return;
        setState("thinking");
        try {
          const { text } = await transcribeAudio(new Blob(chunks, { type: recorder.mimeType }), controller.signal);
          if (!active()) return;
          if (!text?.trim()) { setState("idle"); return; }
          await answer(text.trim(), controller, active);
        } catch (caught) {
          if (active()) { if (caught.name !== "AbortError") setError(caught.message); setState("idle"); }
        }
      };
      recorder.start();
      const started = Date.now();
      let heardSpeech = false, lastSound = started;
      r.timer = setInterval(() => {
        const levels = getMicLevels();
        const energy = levels?.reduce((a, b) => a + b, 0) / (levels?.length || 1);
        if (energy > 9) { heardSpeech = true; lastSound = Date.now(); }
        if ((heardSpeech && Date.now() - lastSound > 1200) || Date.now() - started > 30000) {
          if (recorder.state === "recording") recorder.stop();
        }
      }, 100);
    } catch (caught) {
      if (active()) { stop(); setError(caught.message); }
    }
  }
  toggleRef.current = toggleMic;

  // Agent awareness, the ChatGPT-Pets half: this window is not the one running
  // the chat, so job status and the pending-approval count both have to arrive
  // over /ws/agents. `done`/`error` are counted rather than flashed because
  // "ready" means finished-and-not-looked-at, which has to survive until the
  // user actually looks.
  useEffect(() => {
    if (headless) return undefined;
    const disconnect = connectAgentSocket(msg => {
      if (msg.type === "snapshot") {
        const active = (msg.jobs || []).filter(j => j.status === "queued" || j.status === "working");
        activeJobs.current = new Set(active.map(j => j.id));
        setAgentActive(active.length > 0);
        setApprovals(msg.approvals_pending || 0);
        return;
      }
      if (msg.type === "approvals") { setApprovals(msg.pending || 0); return; }
      if (msg.type !== "job") return;
      const job = msg.job;
      const was = activeJobs.current.has(job.id);
      if (job.status === "queued" || job.status === "working") {
        activeJobs.current.add(job.id);
      } else {
        activeJobs.current.delete(job.id);
        if (was && job.status === "done") setUnreadDone(n => n + 1);
        if (was && job.status === "error") setUnreadFailed(n => n + 1);
      }
      setAgentActive(activeJobs.current.size > 0);
    });
    return disconnect;
  }, [headless]);

  // Re-read on hover as well as on mount: a monitor can be plugged in or
  // unplugged while the pet is sitting there, and the button should appear or
  // disappear to match rather than stay stale until the window is reopened.
  useEffect(() => {
    if (headless) return;
    window.electronAPI?.miniplayerDisplays?.().then(setDisplays).catch(() => {});
  }, [headless, hovered]);


  useEffect(() => {
    getAppSettings().then(value => { settings.current = value; }).catch(() => {});
    const unsub = window.electronAPI?.onPushToTalkTriggered?.(() => toggleRef.current?.());
    const interrupted = () => stop();
    window.addEventListener("nova-voice-interrupted", interrupted);
    const escape = e => { if (e.key === "Escape") stop(); };
    window.addEventListener("keydown", escape);
    return () => { unsub?.(); window.removeEventListener("keydown", escape); window.removeEventListener("nova-voice-interrupted", interrupted); stop(); stopWakeWordDetection(); };
  }, []);

  useEffect(() => {
    if (!wake || state !== "idle") { stopWakeWordDetection(); setWakeReady(false); return; }
    let disposed = false;
    const arm = async () => {
      try {
        const ready = await startWakeWordDetection(() => { if (!disposed) toggleRef.current?.(); }, caught => { if (!disposed) { setError(caught.message); setWakeReady(false); } });
        if (!disposed) setWakeReady(Boolean(ready));
      } catch (caught) { if (!disposed) { setWakeReady(false); if (!caught.message.includes("another Nova window")) setError(caught.message); } }
    };
    arm();
    const timer = setInterval(arm, 3000);
    return () => { disposed = true; clearInterval(timer); stopWakeWordDetection(); };
  }, [wake, state]);

  const status = { idle: !wake ? "Microphone paused" : wakeReady ? "Listening for Hey Nova" : "Wake listener on standby", listening: "Listening… pause to send", thinking: "Working…", speaking: "Speaking" };
  // Header voice-status cluster. The error used to be rendered through the
  // same neutral `text-charcoal-300` span as an ordinary status line, so a
  // real failure ("Requested device not found") was visually indistinguishable
  // from "Listening for Hey Nova" -- it read as a stray sentence pinned to the
  // top of every screen rather than as something wrong. A state dot plus an
  // alert colour makes the three cases (working / paused / failed) legible at
  // a glance, and role="alert" gets the failure to a screen reader.
  if (headless) {
    const dotClass = error
      ? "bg-rose-400"
      : state === "idle"
        ? wake && wakeReady
          ? "bg-emerald-400"
          : "bg-charcoal-500"
        : "bg-emerald-400 animate-pulse motion-reduce:animate-none";
    return (
      // At 375px this cluster shares one 48px row with the wordmark and the
      // breadcrumb. It was fixed-width, so the whole thing ran past the right
      // edge and got clipped -- the status text and the mic button both ended
      // up off screen, which is worse than showing less of the sentence. Now
      // the text is what gives way (a short truncation on a phone, the full
      // line from sm: up) and the buttons, which are the only part you can
      // act on, never shrink.
      <div className="ml-auto flex min-w-0 shrink items-center gap-2 text-xs sm:gap-2.5">
        <span
          role={error ? "alert" : "status"}
          className={`flex min-w-0 items-center gap-1.5 ${error ? "text-rose-300" : "text-charcoal-300"}`}
        >
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} aria-hidden="true" />
          <span className="truncate sm:max-w-[280px]" title={error || status[state]}>
            {error || status[state]}
          </span>
        </span>
        <button
          aria-label={wake ? "Pause wake words" : "Resume wake words"}
          onClick={() => { stop(); setError(""); setWake(!wake); }}
          className="shrink-0 rounded-md px-2 py-1 text-charcoal-300 ring-1 ring-charcoal-600 transition-colors hover:bg-charcoal-800 hover:text-charcoal-100"
        >
          {wake ? "Pause mic" : "Resume mic"}
        </button>
        {state !== "idle" && (
          <button
            onClick={stop}
            className="shrink-0 rounded-md px-2 py-1 text-rose-300 ring-1 ring-rose-400/40 transition-colors hover:bg-rose-500/10"
          >
            Stop
          </button>
        )}
      </div>
    );
  }
  // Per-state accent, used for the status text, the pulse ring behind the
  // character and the mic button's tint -- one colour cue in three places
  // reads as a single state change rather than three unrelated animations.
  const accent = {
    idle: { ring: "rgba(52,211,153,0.16)", text: "text-charcoal-300", dot: "bg-emerald-400/70" },
    listening: { ring: "rgba(96,165,250,0.30)", text: "text-sky-200", dot: "bg-sky-400" },
    thinking: { ring: "rgba(167,139,250,0.30)", text: "text-violet-200", dot: "bg-violet-400" },
    speaking: { ring: "rgba(52,211,153,0.32)", text: "text-emerald-200", dot: "bg-emerald-400" },
  }[state] || { ring: "rgba(52,211,153,0.16)", text: "text-charcoal-300", dot: "bg-emerald-400/70" };
  const busy = state !== "idle";

  // ChatGPT's priority, in its order.
  const agentKey =
    approvals > 0 ? "needs_input"
      : unreadFailed > 0 ? "blocked"
        : unreadDone > 0 ? "ready"
          : agentActive ? "working"
            : null;
  const agent = agentKey ? AGENT_STATUS[agentKey] : null;
  // Shown only while this window is otherwise idle: a live voice turn already
  // owns the character's pose, glow and status line, and always wins.
  const showAgent = Boolean(agent) && !busy;
  const agentBadge = agentKey === "needs_input" && approvals > 1 ? String(approvals) : agent?.badge;
  // Looking at the character is what marks finished work as read. Approvals
  // are deliberately excluded -- those need a real answer in the chat window,
  // and clearing them here would hide something still blocking the run.
  const acknowledge = () => { setUnreadDone(0); setUnreadFailed(0); };


  return (
    <main
      className="flex h-screen w-full flex-col items-center justify-center p-3 select-none text-charcoal-100 font-sans"
      style={{ WebkitAppRegion: "drag", background: "transparent" }}
      onMouseEnter={() => { setHovered(true); acknowledge(); }}
      onMouseLeave={() => { setHovered(false); if (!draft.trim()) setComposing(false); }}
    >
      <div ref={cardRef} className={`p-minicard${prefs.dark ? " night" : ""} w-full max-w-[270px] rounded-2xl p-3.5 flex flex-col items-center gap-2`}>
        
        {/* Top Header Row */}
        <div className="flex w-full items-center justify-between text-xs text-charcoal-400 border-b border-charcoal-800/60 pb-2" style={{ WebkitAppRegion: "no-drag" }}>
          <div className="flex items-center gap-1.5 font-medium text-charcoal-200">
            <NovaLogo size={15} animate={busy} />
            <span className="text-[12px] font-semibold tracking-wide">N.O.V.A.</span>
          </div>

          <div className="flex items-center gap-1">
            {/* Pin Toggle Button */}
            <button
              onClick={togglePin}
              title={pinned ? "Pinned on top. Click for a normal window" : "Normal window. Click to keep on top"}
              aria-label={pinned ? "Unpin from top" : "Pin on top"}
              aria-pressed={pinned}
              className={`rounded p-1 transition-colors ${
                pinned ? "bg-cyan-500/20 text-cyan-300" : "text-charcoal-500 hover:text-charcoal-300 hover:bg-charcoal-800"
              }`}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="17" x2="12" y2="22"></line>
                <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"></path>
              </svg>
            </button>

            {/* Expand to Full App */}
            <button
              onClick={() => window.electronAPI?.focusMainWindow?.()}
              title="Open full N.O.V.A. app"
              aria-label="Open the full app"
              className="rounded p-1 text-charcoal-500 hover:text-charcoal-300 hover:bg-charcoal-800 transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="M9 3v18" />
              </svg>
            </button>

            {/* Close */}
            <button
              onClick={() => window.electronAPI?.closeMiniplayer?.()}
              title="Close miniplayer"
              aria-label="Close miniplayer"
              className="rounded p-1 text-charcoal-500 hover:text-rose-400 hover:bg-charcoal-800 transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </div>

        {/* Central Reactor Core Area */}
        <div
          className="relative w-44 h-44 flex items-center justify-center cursor-pointer transition-transform hover:scale-[1.02]"
          style={{ WebkitAppRegion: "drag" }}
          onClick={() => { acknowledge(); busy ? stop() : toggleMic(); }}
          title={busy ? "Click to stop" : "Click to talk"}
        >
          <div className="relative w-full h-full">
            <Reactor className="p-mini-reactor" palette={prefs.palette} dark={prefs.dark}
              state={state === "idle" || state === "listening" || state === "thinking" || state === "speaking" ? state : "thinking"} label="Nova" />
          </div>
        </div>

        {/* Status Line */}
        <div className="text-center w-full px-2" style={{ WebkitAppRegion: "no-drag" }}>
          <div className="flex items-center justify-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${accent.dot} animate-pulse`} />
            <span className={`text-[12px] font-medium ${accent.text}`}>
              {showAgent ? agent.label : status[state]}
            </span>
          </div>

          {transcript && (
            <p className="mt-1 line-clamp-2 text-[11px] text-charcoal-400 font-mono italic">
              "{transcript}"
            </p>
          )}
          {error && (
            <p className="mt-1 text-[11px] text-rose-300 font-medium">
              {error}
            </p>
          )}

          {upcomingAssignment && (
            <div
              className="mx-auto mt-2 max-w-[200px] truncate rounded-full bg-charcoal-800/80 border border-charcoal-700/60 px-2.5 py-0.5 text-[10px] text-zinc-300 flex items-center justify-center gap-1 cursor-pointer hover:border-zinc-500 transition-colors"
              onClick={() => window.electronAPI?.focusMainWindow?.()}
              title={`Due: ${new Date(upcomingAssignment.due_at).toLocaleDateString()} — Click to open in Nova`}
            >
              <span className="text-amber-400 shrink-0">⚡</span>
              <span className="truncate">{upcomingAssignment.title}</span>
            </div>
          )}
        </div>

        {/* Bottom Action Controls */}
        <div className="w-full space-y-2 pt-1" style={{ WebkitAppRegion: "no-drag" }}>
          {composing ? (
            <input
              id="nova-quick-chat"
              autoFocus
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && draft.trim()) {
                  e.preventDefault();
                  const text = draft.trim();
                  setDraft("");
                  setComposing(false);
                  acknowledge();
                  ask(text);
                }
                if (e.key === "Escape") { setComposing(false); setDraft(""); }
              }}
              onBlur={() => { if (!draft.trim()) setComposing(false); }}
              placeholder="Ask Nova anything…"
              className="w-full rounded-xl bg-charcoal-900 border border-charcoal-800 px-3 py-2 text-[12px] text-charcoal-100 placeholder:text-charcoal-500 focus:border-cyan-500/60 focus:outline-none"
            />
          ) : (
            <div className="flex w-full items-center gap-2">
              <button
                onClick={() => { acknowledge(); setComposing(true); }}
                title="Type a question"
                className="flex items-center justify-center rounded-xl bg-charcoal-900 border border-charcoal-800 px-3 py-2 text-charcoal-300 hover:text-charcoal-100 hover:bg-charcoal-800 transition-colors"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z" />
                </svg>
              </button>

              <button
                onClick={() => { acknowledge(); busy ? stop() : toggleMic(); }}
                className={`flex flex-1 items-center justify-center gap-2 rounded-xl py-2 text-[12px] font-semibold transition-all ${
                  busy
                    ? "bg-rose-500/20 text-rose-300 border border-rose-500/30 hover:bg-rose-500/30"
                    : "text-white shadow-sm border border-transparent hover:opacity-90"
                }`}
                style={!busy ? { backgroundColor: "var(--accent, #3B82F6)" } : {}}
              >
                {busy ? "Stop" : "Talk to Nova"}
              </button>
            </div>
          )}

          {/* Quick options: Hey Nova toggle + display switch */}
          <div className="flex items-center justify-between text-[11px] text-charcoal-500 px-1 pt-0.5">
            <label className="flex items-center gap-1.5 cursor-pointer hover:text-charcoal-300">
              <input
                type="checkbox"
                checked={wake}
                onChange={e => { setError(""); setWake(e.target.checked); }}
                className="h-3 w-3 accent-cyan-500 rounded"
              />
              <span>"Hey Nova"</span>
            </label>

            {displays.count > 1 && (
              <button
                onClick={() =>
                  window.electronAPI?.moveMiniplayerToNextDisplay?.()
                    .then(res => res && setDisplays(res))
                    .catch(() => {})
                }
                className="hover:text-charcoal-300 text-[10.5px]"
                title="Move miniplayer to next screen"
              >
                Screen {displays.index + 1}/{displays.count}
              </button>
            )}
          </div>
        </div>

      </div>
    </main>
  );

}
