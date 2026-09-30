import { useEffect, useRef, useState } from "react";
import { chatAttachmentDownloadUrl, textToSpeech, transcribeAudio, uploadChatAttachment } from "../api.js";
import { openMicrophone } from "../lib/microphone.js";
import { attachMicAnalyser, detachMicAnalyser } from "../lib/micLevels.js";
import { playTtsAudio, stopTtsAudio } from "../lib/ttsPlayback.js";
import Guide, { GuideButton } from "./Guide.jsx";
import Icon from "./icons.jsx";
import Markdown from "./Markdown.jsx";
import Reactor from "./Reactor.jsx";
import { loadChat, refreshChat, sendMessage, stopMessage, takePrefill, useChat } from "./chatStore.js";
import { chatStatus } from "./paperApi.js";
import { setListening } from "./novaState.js";
import { useUi } from "./ui.jsx";
import { keys } from "./keys.js";

function day(ts) {
  const d = ts ? new Date(ts.includes("T") ? ts : `${ts.replace(" ", "T")}Z`) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
}

function dividerLabel(d) {
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `Today · ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })} · ${time}`;
}

const plain = (text = "") => text.replace(/\n*⏹ Stopped\.\s*$/, "");

function Reply({ m, onMenu, onCopy, onSpeak, speaking }) {
  if (m.pending && !m.content && !m.error) {
    return <div className="p-thinking">Nova is thinking…</div>;
  }
  const when = day(m.created_at);
  return (
    <div className={`p-n${m.error && !m.content ? " error" : ""}`} onContextMenu={onMenu}>
      {m.content ? <Markdown text={plain(m.content)} /> : null}
      {m.error ? <p className="err">{m.error}</p> : null}
      {(m.stopped || /⏹ Stopped\.\s*$/.test(m.content || "")) && <span className="stopped">Stopped</span>}
      {m.attachments?.length ? (
        <div className="p-atts">
          {m.attachments.map((a) => (
            <a key={a.id} className="p-att" href={chatAttachmentDownloadUrl(a.id)} target="_blank" rel="noreferrer">{a.filename || a.name || "Attachment"}</a>
          ))}
        </div>
      ) : null}
      {m.content && !m.pending ? (
        <div className="p-msgacts">
          <button className="p-link" onClick={onCopy} aria-label="Copy reply" title="Copy reply"><Icon name="copy" size={14} /></button>
          <button className="p-link" onClick={onSpeak} aria-label={speaking ? "Stop reading" : "Read aloud"} title={speaking ? "Stop reading" : "Read aloud"}>
            <Icon name={speaking ? "stop" : "voice"} size={14} />
          </button>
          {when ? <span className="when" title={when.toLocaleString()}>{when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

export default function ChatView({ conversationId, onConversation, title, palette, dark, expanded, onToggleExpand, onNewChat, voiceId, muted, onToggleMute, remoteName }) {
  const ui = useUi();
  const chat = useChat(conversationId);
  const [text, setText] = useState("");
  const [pending, setPending] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [notice, setNotice] = useState("");
  const [speaking, setSpeaking] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const threadRef = useRef(null);
  const fileRef = useRef(null);
  const recorderRef = useRef(null);
  const inputRef = useRef(null);
  const running = chat.busy || chat.remoteRunning;
  const last = chat.messages[chat.messages.length - 1];

  useEffect(() => { if (conversationId != null) loadChat(conversationId); }, [conversationId]);
  useEffect(() => { inputRef.current?.focus(); }, [conversationId]);
  useEffect(() => { const t = takePrefill(); if (t) setText(t); }, []);
  // A prefill that arrives while this view is already open ("Ask Nova about this").
  useEffect(() => {
    const onPrefill = () => { const t = takePrefill(); if (t) { setText(t); inputRef.current?.focus(); } };
    window.addEventListener("nova-prefill", onPrefill);
    return () => window.removeEventListener("nova-prefill", onPrefill);
  }, []);
  useEffect(() => () => { stopTtsAudio(); }, []);

  // A turn still running from before a reload: watch it until it ends.
  useEffect(() => {
    if (!chat.remoteRunning || chat.busy || conversationId == null) return undefined;
    const t = setInterval(async () => {
      const s = await chatStatus(conversationId).catch(() => null);
      if (s && !s.running) refreshChat(conversationId);
    }, 2500);
    return () => clearInterval(t);
  }, [chat.remoteRunning, chat.busy, conversationId]);

  // Stay on the newest message while it streams, unless you've scrolled up.
  const pinned = useRef(true);
  useEffect(() => {
    const el = threadRef.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [chat.messages.length, last?.content, conversationId]);

  const onScroll = () => {
    const el = threadRef.current;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setAtBottom(pinned.current);
  };
  const toLatest = () => {
    const el = threadRef.current;
    pinned.current = true;
    el?.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const copyText = (value) => navigator.clipboard.writeText(plain(value)).then(() => ui.toast("Copied."));

  async function speak(m, key) {
    if (speaking === key) { stopTtsAudio(); setSpeaking(null); return; }
    setSpeaking(key);
    try {
      const blob = await textToSpeech(plain(m.content), voiceId || null);
      await playTtsAudio(blob, { onEnd: () => setSpeaking((k) => (k === key ? null : k)) });
    } catch (e) {
      setSpeaking(null);
      ui.toast(`Couldn't read it aloud: ${e.message}`, { error: true });
    }
  }

  const messageMenu = (e, m, key) => {
    const selected = String(window.getSelection?.() || "").trim();
    ui.openMenu(e, [
      selected && { label: "Copy selection", icon: "copy", shortcut: keys("Ctrl+C"), onSelect: () => navigator.clipboard.writeText(selected) },
      { label: m.role === "user" ? "Copy message" : "Copy reply", icon: "copy", onSelect: () => copyText(m.content) },
      m.role !== "user" && { label: speaking === key ? "Stop reading" : "Read aloud", icon: "voice", onSelect: () => speak(m, key) },
      m.role === "user" && { label: "Edit and send again", icon: "edit", onSelect: () => { setText(m.content); inputRef.current?.focus(); } },
      "-",
      { label: "New chat", icon: "plus", shortcut: keys("Ctrl+N"), onSelect: onNewChat },
    ]);
  };

  async function attach(files) {
    const list = [...files].slice(0, 8);
    if (!list.length) return;
    setUploading(true);
    try {
      for (const file of list) {
        const saved = await uploadChatAttachment(file);
        setPending((p) => [...p, { id: saved.id, filename: saved.filename || file.name || "Pasted image" }]);
      }
    } catch (error) {
      setNotice(error.message);
    } finally {
      setUploading(false);
    }
  }

  async function submit() {
    const body = text.trim();
    if (!body || running) return;
    setText("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    const atts = pending;
    setPending([]);
    setNotice("");
    pinned.current = true;
    try {
      await sendMessage(conversationId, body, atts, { onCreated: onConversation });
    } catch (error) {
      setNotice(error.message);
    }
  }

  async function onFile(event) {
    const files = [...(event.target.files || [])];
    event.target.value = "";
    await attach(files);
  }

  async function toggleMic() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    try {
      stopTtsAudio();
      const stream = await openMicrophone();
      const recorder = new MediaRecorder(stream);
      const chunks = [];
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        detachMicAnalyser();
        setListening(false);
        setRecording(false);
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        if (!blob.size) return;
        try {
          const { text: heard } = await transcribeAudio(blob);
          if (heard) setText((t) => (t ? `${t} ${heard}` : heard));
        } catch (error) {
          setNotice(`Couldn't hear that: ${error.message}`);
        }
      };
      recorderRef.current = recorder;
      attachMicAnalyser(stream);
      setListening(true);
      setRecording(true);
      recorder.start();
    } catch (error) {
      setListening(false);
      setRecording(false);
      setNotice(`Microphone unavailable: ${error.message}`);
    }
  }

  const now = new Date();
  let lastDay = null;

  return (
    <section className={`p-chat${dragging ? " dropping" : ""}`} aria-label="Chat"
      onDragOver={(e) => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false); }}
      onDrop={(e) => { if (e.dataTransfer?.files?.length) { e.preventDefault(); setDragging(false); attach(e.dataTransfer.files); } }}>
      {dragging && <div className="p-drop">Drop to attach</div>}
      <div className="p-cbar">
        <span className="ttl">{title || "New conversation"}</span>
        {last?.label ? <span className="model">{last.label}</span> : null}
        {remoteName && <span className="p-remotebadge" title={`This chat runs on ${remoteName}`}><i />Remote · {remoteName}</span>}
        <span className="sp" />
        <GuideButton id="chat" />
        {onToggleMute && (
          <button className={`p-ib${muted ? " on" : ""}`} data-tour="mute" onClick={onToggleMute} aria-pressed={Boolean(muted)}
            aria-label={muted ? "Let Nova speak" : "Mute Nova"} title={muted ? "Nova is muted. Click to let it speak" : "Mute Nova (it keeps writing)"}>
            <Icon name={muted ? "muted" : "speaker"} />
          </button>
        )}
        <button className="p-ib" onClick={onToggleExpand} aria-label={expanded ? "Return to normal view" : "Expand chat"} title={expanded ? "Return (Esc)" : "Expand chat"}>
          <Icon name={expanded ? "shrink" : "grow"} />
        </button>
        <button className="p-btn" onClick={onNewChat} title={keys("New chat (Ctrl+N)")}>New chat</button>
      </div>
      <div className="p-rstage"><Reactor palette={palette} dark={dark} label="Nova" /></div>
      <div className="scroll p-thread" ref={threadRef} onScroll={onScroll}>
        <span className="p-vert l">{now.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })}</span>
        <span className="p-vert r">{now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase()}</span>
        <div className="p-col">
          {conversationId == null && (
            <div className="p-empty">
              <div className="muted">Ask Nova anything, or tell it what to do.</div>
            </div>
          )}
          {conversationId == null && <Guide id="chat" onTry={(t) => { setText(t); inputRef.current?.focus(); }} />}
          {chat.error && <div className="err">{chat.error}</div>}
          {chat.messages.map((m, i) => {
            const d = day(m.created_at);
            const key = m.id || `m${i}`;
            let divider = null;
            if (d && (!lastDay || d - lastDay > 30 * 60 * 1000)) divider = <div className="p-divider">{dividerLabel(d)}</div>;
            if (d) lastDay = d;
            return (
              <div key={key} style={{ display: "contents" }}>
                {divider}
                {m.role === "user"
                  ? <div className="p-u" onContextMenu={(e) => messageMenu(e, m, key)}>{m.content}{m.attachments?.length ? <div className="p-atts">{m.attachments.map((a) => <span key={a.id} className="p-att">{a.filename || a.name}</span>)}</div> : null}</div>
                  : <Reply m={m} speaking={speaking === key} onMenu={(e) => messageMenu(e, m, key)} onCopy={() => copyText(m.content)} onSpeak={() => speak(m, key)} />}
              </div>
            );
          })}
        </div>
      </div>
      <div className="p-composer-wrap">
        {!atBottom && chat.messages.length > 0 && (
          <button className="p-latest" onClick={toLatest} aria-label="Jump to the latest message"><Icon name="down" size={14} />Latest</button>
        )}
        {pending.length > 0 && (
          <div className="p-pending">{pending.map((a) => (
            <button key={a.id} className="p-att" onClick={() => setPending((p) => p.filter((x) => x.id !== a.id))} title="Remove attachment" aria-label={`Remove ${a.filename}`}>{a.filename} ×</button>
          ))}</div>
        )}
        {notice && <div className="err">{notice}</div>}
        <div className="p-composer">
          <input ref={fileRef} type="file" hidden multiple onChange={onFile} />
          <button className="p-ib plain" onClick={() => fileRef.current?.click()} aria-label="Attach files" title="Attach files (or drop them here, or paste an image)" disabled={uploading}><Icon name="clip" /></button>
          <textarea
            ref={inputRef}
            rows={1}
            value={text}
            aria-label="Message Nova"
            placeholder={uploading ? "Attaching…" : recording ? "Listening…" : "Message Nova"}
            onChange={(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(180, e.target.scrollHeight)}px`; }}
            onPaste={(e) => {
              const files = [...(e.clipboardData?.files || [])];
              if (files.length) { e.preventDefault(); attach(files); }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
              // Up in an empty box brings back your last message to fix it.
              if (e.key === "ArrowUp" && !text) {
                const mine = [...chat.messages].reverse().find((x) => x.role === "user");
                if (mine) { e.preventDefault(); setText(mine.content); }
              }
              if (e.key === "Escape" && running) { e.preventDefault(); stopMessage(conversationId); }
            }}
          />
          <button className={`p-ib plain${recording ? " rec" : ""}`} onClick={toggleMic} aria-label={recording ? "Stop recording" : "Speak"} title={recording ? "Stop recording" : "Speak your message"}><Icon name="mic" /></button>
          {running ? (
            <button className="p-send stop" onClick={() => stopMessage(conversationId)} aria-label="Stop Nova" title="Stop Nova (Esc)"><Icon name="stop" /></button>
          ) : (
            <button className="p-send" onClick={submit} disabled={!text.trim()} aria-label="Send" title="Send (Enter)"><Icon name="arrow" /></button>
          )}
        </div>
      </div>
    </section>
  );
}
