// Nova's conversation inside Studio: the same streaming, rendering and
// send/stop as Chat, with the files Nova changes handed to Studio's Changes.
// It can include the open file as context, and starts a code chat on the
// first message if there isn't one yet.
import { useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import Markdown from "./Markdown.jsx";
import { loadChat, sendMessage, stopMessage, useChat } from "./chatStore.js";
import { useUi } from "./ui.jsx";

export default function CodeChat({ conversationId, onFileChanges, onResponseDone, activePath, prefill, onPrefillUsed, onNeedConversation }) {
  const ui = useUi();
  const chat = useChat(conversationId);
  const [text, setText] = useState("");
  const [withFile, setWithFile] = useState(true);
  const [notice, setNotice] = useState("");
  const threadRef = useRef(null);
  const inputRef = useRef(null);
  const running = chat.busy || chat.remoteRunning;
  const last = chat.messages[chat.messages.length - 1];

  useEffect(() => { if (conversationId != null) loadChat(conversationId); }, [conversationId]);
  useEffect(() => { const el = threadRef.current; if (el) el.scrollTop = el.scrollHeight; }, [chat.messages.length, last?.content]);
  useEffect(() => { if (prefill) { setText(prefill); onPrefillUsed?.(); inputRef.current?.focus(); } }, [prefill, onPrefillUsed]);

  async function submit() {
    const body = text.trim();
    if (!body || running) return;
    setText("");
    setNotice("");
    try {
      const id = conversationId ?? await onNeedConversation?.();
      if (id == null) return;
      const message = withFile && activePath ? `[Open file in Studio: ${activePath}]\n${body}` : body;
      await sendMessage(id, message, [], {
        tab: "code",
        onEvent: (event, cid) => { if (event.type === "file_changes") onFileChanges?.(cid, event.changes || []); },
      });
      onResponseDone?.();
    } catch (error) {
      setNotice(error.message);
    }
  }

  const show = (content = "") => content.replace(/^\[Open file in Studio: [^\]]+\]\n/, "");

  return (
    <div className="p-codechat-body">
      <div className="scroll" ref={threadRef}>
        {chat.messages.length === 0 && (
          <div className="p-empty">
            <div className="muted">Ask Nova to change, explain, or build something in this project.</div>
          </div>
        )}
        {chat.messages.map((m, i) => (m.role === "user"
          ? <div key={m.id || i} className="p-u" onContextMenu={(e) => ui.openMenu(e, [
              { label: "Copy", icon: "copy", onSelect: () => navigator.clipboard.writeText(show(m.content)) },
              { label: "Edit and send again", icon: "edit", onSelect: () => setText(show(m.content)) },
            ])}>{show(m.content)}</div>
          : (
            <div key={m.id || i} className="p-n" onContextMenu={(e) => ui.openMenu(e, [
              { label: "Copy reply", icon: "copy", onSelect: () => navigator.clipboard.writeText(m.content || "").then(() => ui.toast("Copied.")) },
            ])}>
              {m.pending && !m.content ? <div className="p-thinking">Nova is working…</div> : <Markdown text={m.content || ""} />}
              {m.error && <p className="err">{m.error}</p>}
            </div>
          )))}
      </div>
      <div className="p-cccompose">
        {notice && <div className="err">{notice}</div>}
        {activePath && (
          <label className="p-ctx">
            <input type="checkbox" checked={withFile} onChange={(e) => setWithFile(e.target.checked)} />
            <span>Include <b className="mono">{activePath.split("/").pop()}</b></span>
          </label>
        )}
        <div className="p-composer" style={{ width: "100%" }}>
          <textarea ref={inputRef} rows={1} value={text} placeholder="Ask Nova about this project" aria-label="Message Nova about this project"
            onChange={(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(160, e.target.scrollHeight)}px`; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
              if (e.key === "Escape" && running) stopMessage(conversationId);
            }} />
          {running
            ? <button className="p-send stop" onClick={() => stopMessage(conversationId)} aria-label="Stop Nova" title="Stop (Esc)"><Icon name="stop" /></button>
            : <button className="p-send" onClick={submit} disabled={!text.trim()} aria-label="Send" title="Send (Enter)"><Icon name="arrow" /></button>}
        </div>
      </div>
    </div>
  );
}
