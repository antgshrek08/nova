import { memo } from "react";
import DesktopEventCard from "./DesktopEventCard.jsx";
import { chatAttachmentDownloadUrl } from "../api.js";
import { PaperclipIcon, PuzzleIcon } from "./icons.jsx";

// Hoisted so it is compiled once for the process rather than re-evaluated on
// every bubble render -- this is tested against every message on every
// streaming frame (see the memo() note at the bottom of this file).
const LEGACY_PROVIDER_ERROR_RE = /^\s*⚠️\s*OpenRouter model[\s\S]*failed:/;

// Visible "thinking" indicator (task: a real animated indicator while a
// response generates, in both Chat and Code -- this component already
// serves both tabs, see ChatWindow's `variant` prop) -- previously just a
// static "…" with no motion, easy to miss and indistinguishable from a
// genuinely stalled request. Three staggered-delay pulsing dots, the same
// visual language as the rest of the app's pulse animations (VoiceReactor,
// Miniplayer's orb).
function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <span className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-charcoal-400"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </span>
      <span className="text-xs text-charcoal-500">Thinking…</span>
    </div>
  );
}

import katex from "katex";

function formatContent(text) {
  if (!text || typeof text !== "string") return text;
  if (!text.includes("$") && !text.includes("\\(") && !text.includes("\\[")) {
    return text;
  }
  const parts = [];
  const regex = /(\$\$[\s\S]*?\$\$|\$[^\$\n]+?\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\))/g;
  let lastIdx = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index));
    }
    const token = match[0];
    const isBlock = token.startsWith("$$") || token.startsWith("\\[");
    let mathStr = "";
    if (token.startsWith("$$") && token.endsWith("$$")) {
      mathStr = token.slice(2, -2).trim();
    } else if (token.startsWith("$") && token.endsWith("$")) {
      mathStr = token.slice(1, -1).trim();
    } else if (token.startsWith("\\[") && token.endsWith("\\]")) {
      mathStr = token.slice(2, -2).trim();
    } else if (token.startsWith("\\(") && token.endsWith("\\)")) {
      mathStr = token.slice(2, -2).trim();
    }

    try {
      const html = katex.renderToString(mathStr, {
        displayMode: isBlock,
        throwOnError: false,
      });
      parts.push(
        <span
          key={match.index}
          className={isBlock ? "block my-2 overflow-x-auto text-center [white-space:normal] [word-break:normal]" : "inline-block px-0.5 [white-space:normal] [word-break:normal] align-baseline"}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      );
    } catch {
      parts.push(token);
    }
    lastIdx = regex.lastIndex;
  }
  if (lastIdx < text.length) {
    parts.push(text.slice(lastIdx));
  }
  return parts;
}

function MessageBubble({ role, content, meta, desktopEvents, attachments }) {
  const isUser = role === "user";
  const legacyProviderError = !isUser && LEGACY_PROVIDER_ERROR_RE.test(content || "");
  const displayContent = legacyProviderError
    ? "That model was unavailable when this request ran. Send your request again to use the updated fallback routing."
    : content;
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        style={isUser ? { backgroundColor: "var(--accent)", color: "#ffffff" } : {}}
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap break-words ${
          isUser ? "font-normal shadow-sm" : "bg-charcoal-800 text-charcoal-100"
        }`}
      >
        {!isUser && meta && (
          <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-charcoal-500">
            <span>{meta.category}</span>
            <span>{meta.label}</span>
            {meta.skills?.map((name) => (
              <span key={name} className="inline-flex items-center gap-1 rounded-full bg-emerald-900/40 px-2 py-0.5 text-emerald-300" title="Skill loaded for this reply">
                <PuzzleIcon />
                {name}
              </span>
            ))}
          </div>
        )}
        {displayContent && <div>{formatContent(displayContent)}</div>}
        {!content && !isUser && !attachments?.length && <ThinkingIndicator />}
        {attachments?.length > 0 && (
          <div className={`flex flex-wrap gap-1.5 ${content ? "mt-1.5" : ""}`}>
            {attachments.map((a) =>
              a.content_type?.startsWith("image/") ? (
                // Real generated image (task 9) or an image the user
                // attached -- shown inline, not just as a download chip,
                // since "here's an image" should look like an image.
                <a key={a.id} href={chatAttachmentDownloadUrl(a.id)} target="_blank" rel="noreferrer">
                  <img
                    src={chatAttachmentDownloadUrl(a.id)}
                    alt={a.filename}
                    className="max-h-64 max-w-full rounded-lg ring-1 ring-charcoal-700"
                  />
                </a>
              ) : (
                <a
                  key={a.id}
                  href={chatAttachmentDownloadUrl(a.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 rounded-full bg-emerald-700/50 px-2.5 py-0.5 text-[11px] text-emerald-100 hover:bg-emerald-700/70"
                  title={`${a.content_type} · ${a.size_bytes} bytes`}
                >
                  <PaperclipIcon />
                  {a.filename}
                </a>
              )
            )}
          </div>
        )}
        {!isUser &&
          desktopEvents?.map((event) => <DesktopEventCard key={event.id || `${event.type}-${event.ts}`} event={event} />)}
      </div>
    </div>
  );
}

// Streaming appends tokens to the LAST message on a requestAnimationFrame
// cadence (see ChatWindow's flushTokenBuffer) -- roughly 60 setMessages calls
// per second. Without memo, each of those re-rendered every bubble in the
// conversation, so the per-frame cost grew with conversation length: a
// 60-message thread meant ~3,600 bubble renders per second, all but one of
// them producing identical output. setMessages rebuilds the array but spreads
// the individual message objects, so every untouched message keeps prop
// identity and a shallow compare correctly skips it.
export default memo(MessageBubble);
