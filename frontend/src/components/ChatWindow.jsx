import React, { useState, useEffect, useRef } from "react";
import ReactorCore from "./chat/ReactorCore.jsx";
import MessageBubble from "./MessageBubble.jsx";
import {
  streamChat,
  getAppSettings,
  updateAppSettings,
  uploadChatAttachment,
  transcribeAudio,
  textToSpeech,
  listModels,
} from "../api.js";
import { openMicrophone } from "../lib/microphone.js";
import { attachMicAnalyser, detachMicAnalyser } from "../lib/micLevels.js";
import { playTtsAudio, stopTtsAudio } from "../lib/ttsPlayback.js";

const UNIVERSAL_STARTERS = [
  {
    title: "⚡ Autopilot Homework",
    subtitle: "Direct browser & homework automation",
    prompt: "Nova open Chrome and go to Canvas and do all open calculus homework",
    tag: "Autopilot",
  },
  {
    title: "🎓 Socratic Tutor",
    subtitle: "Step-by-step problem guidance & hints",
    prompt: "Guide me step-by-step through solving this homework problem without giving the final answer immediately.",
    tag: "Tutor",
  },
  {
    title: "📄 Research Essay Draft",
    subtitle: "Evidence-backed draft with scholarly citations",
    prompt: "Help me research and write a structured rough draft for my academic essay, complete with verified scholarly citations.",
    tag: "Writing",
  },
  {
    title: "💻 Code & Free Web Ship",
    subtitle: "Interactive app building & zero-API deploy",
    prompt: "Help me design an interactive web app and deploy it for free to Vercel or Netlify.",
    tag: "Studio",
  },
];

export default function ChatWindow({
  conversationId,
  variant = "chat",
  onResponseDone,
  onSendToCode,
  connected = true,
  onEnsureConversation,
  onNewConversation,
  onFileChanges,
}) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [homeworkMode, setHomeworkMode] = useState("tutor"); // "tutor" | "solve"
  const [reactorState, setReactorState] = useState("idle"); // idle, listening, thinking, speaking, automating
  const [primaryModel, setPrimaryModel] = useState("auto");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [listening, setListening] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);

  const bottomRef = useRef(null);
  const fileInputRef = useRef(null);
  const mediaRecorderRef = useRef(null);

  // Load app settings (primary model, homework mode, voice)
  useEffect(() => {
    getAppSettings().then((s) => {
      if (s?.homework_mode) setHomeworkMode(s.homework_mode);
      if (s?.primary_model) setPrimaryModel(s.primary_model);
      if (typeof s?.voice_replies === "boolean") setVoiceEnabled(s.voice_replies);
    }).catch(() => {});
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const handleToggleHomeworkMode = async (mode) => {
    setHomeworkMode(mode);
    try {
      await updateAppSettings({ homework_mode: mode });
    } catch {}
  };

  const handleToggleVoice = async () => {
    const next = !voiceEnabled;
    setVoiceEnabled(next);
    try {
      await updateAppSettings({ voice_replies: next });
    } catch {}
  };

  const handleAttachmentUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingAttachment(true);
    try {
      const convId = conversationId || (await onEnsureConversation?.());
      const res = await uploadChatAttachment(file);
      setAttachments((prev) => [...prev, { id: res.id, filename: file.name, size: file.size }]);
    } catch (err) {
      console.error("Upload error:", err);
    } finally {
      setUploadingAttachment(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleMicToggle = async () => {
    if (listening) {
      mediaRecorderRef.current?.stop();
      return;
    }

    try {
      stopTtsAudio();
      setReactorState("listening");
      const stream = await openMicrophone();
      const recorder = new MediaRecorder(stream);
      const chunks = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        detachMicAnalyser();
        setListening(false);
        setReactorState("thinking");

        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        if (blob.size > 0) {
          try {
            const { text } = await transcribeAudio(blob);
            if (text) {
              setInput((prev) => (prev ? `${prev} ${text}` : text));
            }
          } catch (err) {
            console.error("Transcription error:", err);
          }
        }
        setReactorState("idle");
      };

      mediaRecorderRef.current = recorder;
      attachMicAnalyser(stream);
      setListening(true);
      recorder.start();
    } catch (err) {
      console.error("Mic error:", err);
      setListening(false);
      setReactorState("idle");
    }
  };

  const handleSendMessage = async (textToSend) => {
    const query = (textToSend || input).trim();
    if (!query || busy) return;

    setInput("");
    const currentAttachmentIds = attachments.map((a) => a.id);
    setAttachments([]);

    // Check query for autopilot intent trigger
    let effectiveHomeworkMode = homeworkMode;
    const lowerQuery = query.toLowerCase();
    if (lowerQuery.includes("solve") || lowerQuery.includes("do my") || lowerQuery.includes("autopilot")) {
      effectiveHomeworkMode = "solve";
      setHomeworkMode("solve");
    } else if (lowerQuery.includes("tutor") || lowerQuery.includes("explain") || lowerQuery.includes("walk me through")) {
      effectiveHomeworkMode = "tutor";
      setHomeworkMode("tutor");
    }

    // Add user message to UI
    const userMsg = {
      role: "user",
      content: query,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setBusy(true);
    setReactorState(effectiveHomeworkMode === "solve" ? "automating" : "thinking");

    let fullAssistantResponse = "";
    const assistantMsgIndex = messages.length + 1;

    try {
      const convId = conversationId || (await onEnsureConversation?.());
      await streamChat(
        convId,
        query,
        (event) => {
          if (event.type === "token") {
            fullAssistantResponse += event.content || "";
            setMessages((prev) => {
              const updated = [...prev];
              if (updated[assistantMsgIndex]) {
                updated[assistantMsgIndex] = {
                  role: "assistant",
                  content: fullAssistantResponse,
                  meta: { model: primaryModel },
                };
              } else {
                updated.push({
                  role: "assistant",
                  content: fullAssistantResponse,
                  meta: { model: primaryModel },
                });
              }
              return updated;
            });
          } else if (event.type === "file_changes") {
            onFileChanges?.(convId, event.changes || []);
          } else if (event.type === "meta") {
            if (event.status_message) {
              setReactorState("automating");
            }
          }
        },
        {
          homework: effectiveHomeworkMode === "solve",
          attachmentIds: currentAttachmentIds,
          overrideModelId: primaryModel !== "auto" ? primaryModel : null,
        }
      );

      setReactorState("idle");
      onResponseDone?.();

      // Voice playback if enabled
      if (voiceEnabled && fullAssistantResponse) {
        setReactorState("speaking");
        try {
          const audioBlob = await textToSpeech(fullAssistantResponse.slice(0, 300));
          await playTtsAudio(audioBlob, { onEnd: () => setReactorState("idle") });
        } catch {
          setReactorState("idle");
        }
      }
    } catch (err) {
      console.error("Chat stream error:", err);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Nova encountered an issue: ${err.message || "Failed to reach AI model."}`,
        },
      ]);
      setReactorState("idle");
    } finally {
      setBusy(false);
    }
  };

  const modelBadgeLabel = primaryModel === "auto"
    ? "✦ Auto-Routed Model"
    : primaryModel.includes("claude")
    ? "✦ Claude 3.5"
    : primaryModel.includes("gpt")
    ? "✦ GPT-4o"
    : primaryModel.includes("gemini")
    ? "✦ Gemini 2.5"
    : primaryModel.includes("ollama")
    ? "✦ Local Ollama"
    : `✦ ${primaryModel}`;

  return (
    <div className="flex h-full flex-col bg-[#090b10] text-[#E2E8F0]">
      {/* Top Header Bar */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#1A1F2C] bg-[#0E121B]/90 px-5 py-3 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
            <h1 className="text-sm font-semibold tracking-wide text-white">Nova Copilot</h1>
          </div>
          <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400">
            {modelBadgeLabel}
          </span>
        </div>

        {/* Center / Right controls: Mode Pill & Actions */}
        <div className="flex items-center gap-3">
          {/* Autopilot vs Tutor Toggle */}
          <div className="flex items-center rounded-lg border border-[#23293D] bg-[#131722] p-0.5 text-xs">
            <button
              type="button"
              onClick={() => handleToggleHomeworkMode("solve")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 font-medium transition-all ${
                homeworkMode === "solve"
                  ? "border border-cyan-500/40 bg-cyan-500/20 text-cyan-300 shadow-sm"
                  : "text-[#8E9EB5] hover:text-white"
              }`}
              title="Nova automates assignments and drives browser directly"
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
              title="Nova tutors you step-by-step with hints without giving away answers"
            >
              <span>🎓 Tutor Mode</span>
            </button>
          </div>

          {/* Voice Toggle */}
          <button
            type="button"
            onClick={handleToggleVoice}
            className={`flex items-center gap-1 rounded-lg border p-1.5 transition-all text-xs ${
              voiceEnabled
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-[#23293D] bg-[#131722] text-[#8E9EB5] hover:text-white"
            }`}
            title={voiceEnabled ? "Voice Output Active" : "Voice Output Muted"}
          >
            <span>{voiceEnabled ? "🔊" : "🔈"}</span>
          </button>

          {/* New Chat Button */}
          <button
            type="button"
            onClick={() => {
              setMessages([]);
              onNewConversation?.();
            }}
            className="flex items-center gap-1.5 rounded-lg border border-[#23293D] bg-[#131722] px-3 py-1 text-xs font-medium text-[#CBD5E1] transition-all hover:bg-[#1A1F2C] hover:text-white"
          >
            <span>+ New</span>
          </button>
        </div>
      </div>

      {/* Main Conversation & Ambient Reactor Area */}
      <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4 sm:px-6">
        {messages.length === 0 ? (
          /* Empty / Welcome State with Central Glowing Reactor */
          <div className="flex flex-1 flex-col items-center justify-center py-6 text-center">
            {/* Ambient Reactor Core */}
            <div className="relative mb-6 flex h-48 w-48 items-center justify-center">
              <div className="absolute inset-0 rounded-full bg-gradient-to-tr from-emerald-500/20 via-cyan-500/15 to-transparent blur-2xl" />
              <div className="relative h-40 w-40">
                <ReactorCore state={reactorState} />
              </div>
            </div>

            <div className="mb-2 flex items-center gap-2">
              <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-400 border border-emerald-500/20">
                {homeworkMode === "solve" ? "⚡ Autopilot Solver Active" : "🎓 Socratic Tutor Active"}
              </span>
            </div>

            <h2 className="text-xl font-bold tracking-tight text-white sm:text-2xl">
              How can Nova help you today?
            </h2>
            <p className="mt-1 max-w-md text-xs text-[#8E9EB5]">
              Ask any academic question, upload homework files, or give Nova commands to control your browser and solve assignments.
            </p>

            {/* Universal Academic Starter Cards */}
            <div className="mt-8 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
              {UNIVERSAL_STARTERS.map((s) => (
                <button
                  key={s.title}
                  type="button"
                  onClick={() => handleSendMessage(s.prompt)}
                  className="group flex flex-col items-start rounded-xl border border-[#1E2433] bg-[#0E121B]/80 p-3.5 text-left transition-all hover:border-emerald-500/50 hover:bg-[#131824] shadow-sm"
                >
                  <div className="flex w-full items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-white group-hover:text-emerald-300 transition-colors">
                      {s.title}
                    </span>
                    <span className="rounded bg-[#1A2030] px-1.5 py-0.5 text-[10px] font-medium text-[#8E9EB5]">
                      {s.tag}
                    </span>
                  </div>
                  <p className="text-[11px] text-[#8E9EB5] group-hover:text-[#CBD5E1] transition-colors leading-relaxed">
                    {s.subtitle}
                  </p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Active Messages View */
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 pb-4">
            {messages.map((m, idx) => (
              <MessageBubble
                key={idx}
                role={m.role}
                content={m.content}
                meta={m.meta}
                onSendToCode={onSendToCode}
              />
            ))}
            {busy && (
              <div className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-300">
                <span className="h-2 w-2 animate-ping rounded-full bg-emerald-400" />
                <span>
                  {reactorState === "automating"
                    ? "Nova is automating task and controlling browser..."
                    : "Nova is reasoning and generating response..."}
                </span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Bottom Composer Bar */}
      <div className="shrink-0 border-t border-[#1A1F2C] bg-[#0B0E15]/95 p-3.5 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl flex-col gap-2">
          {/* Active Attachments Preview */}
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 px-1">
              {attachments.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center gap-1.5 rounded-md border border-[#23293D] bg-[#141824] px-2.5 py-1 text-xs text-[#CBD5E1]"
                >
                  <span>📎 {a.filename}</span>
                  <button
                    type="button"
                    onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== a.id))}
                    className="text-[#8E9EB5] hover:text-rose-400"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Input Box Row */}
          <div className="relative flex items-center rounded-xl border border-[#23293D] bg-[#121622] p-1.5 shadow-inner focus-within:border-emerald-500/60 focus-within:ring-1 focus-within:ring-emerald-500/40">
            {/* File Attachment Hidden Input & Button */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleAttachmentUpload}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingAttachment}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-[#8E9EB5] hover:bg-[#1A2030] hover:text-white transition-all disabled:opacity-50"
              title="Attach PDF, Syllabus, or Image"
            >
              <span>{uploadingAttachment ? "⏳" : "📎"}</span>
            </button>

            {/* Main Text Input */}
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              rows={1}
              placeholder={
                homeworkMode === "solve"
                  ? "Ask Nova or type: 'nova open Chrome and do my calculus homework'..."
                  : "Ask Nova to tutor you through a concept, equation, or draft..."
              }
              className="min-h-[38px] max-h-32 flex-1 resize-none bg-transparent px-3 py-2 text-xs text-white placeholder-[#5E6D82] focus:outline-none leading-relaxed"
            />

            {/* Mic Toggle Button */}
            <button
              type="button"
              onClick={handleMicToggle}
              className={`flex h-9 w-9 items-center justify-center rounded-lg transition-all ${
                listening
                  ? "bg-rose-500 text-white animate-pulse"
                  : "text-[#8E9EB5] hover:bg-[#1A2030] hover:text-white"
              }`}
              title={listening ? "Stop Listening" : "Voice Input (Speech-to-Text)"}
            >
              <span>{listening ? "⏹" : "🎙"}</span>
            </button>

            {/* Send Button */}
            <button
              type="button"
              onClick={() => handleSendMessage()}
              disabled={!input.trim() || busy}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500 font-semibold text-slate-950 shadow-md transition-all hover:bg-emerald-400 disabled:opacity-30 disabled:hover:bg-emerald-500"
              title="Send Message"
            >
              <span>↑</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
