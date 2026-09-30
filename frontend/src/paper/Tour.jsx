// The optional tour, offered once after onboarding: a spotlight on each part
// of Nova with a line or two about it, including the small things nobody
// finds alone (tap the reactor to stop Nova talking, the mute button, Ctrl+K).
// Works on the phone layout too; a step whose target isn't on screen is shown
// in the middle instead of being skipped.
import { useEffect, useLayoutEffect, useState } from "react";
import Icon from "./icons.jsx";
import { IS_MAC, STOP_KEY, keys } from "./keys.js";
import { IS_REMOTE } from "./remote.js";
import { Overlay } from "./ui.jsx";

const phone = () => window.matchMedia?.("(max-width: 640px)").matches;

export function tourSteps() {
  const small = phone();
  return [
    { target: small ? ".p-tabbar" : ".p-nav", title: "Your places",
      text: small ? "Remote (chat with your computer's Nova), Academics, Agents and Memory are down here. Menu has Studio, your chats and Settings."
        : "Chat, Academics, Studio, Agents and Memory. Your past chats are listed under Earlier." },
    { target: ".p-composer", title: "Talk to Nova",
      text: "Type here, or press the microphone and speak. Nova picks the right model for each message, and can do things, not just answer." },
    { target: ".p-rstage canvas", title: "Tap Nova to hush it",
      text: "While Nova is talking, tap its reactor and it stops right away and goes quiet." },
    { target: "[data-tour=mute]", title: "Mute Nova",
      text: "Nova keeps writing but stops speaking. It stays muted, even after you reopen Nova, until you turn it back on." },
    { target: small ? null : ".p-searchbtn", title: "Jump anywhere",
      text: keys(`Press Ctrl+K (${IS_MAC ? "⌘K" : "Ctrl+K"}) to search every screen, setting and command. Ctrl+/ lists all shortcuts.`) },
    { target: ".p-guidebtn", title: "Help on every screen",
      text: "Each screen has this ⓘ button. It shows a short guide for that screen whenever you want it." },
    { target: small ? ".p-tabbar button:nth-child(3)" : ".p-nav .p-item[aria-label=Agents]", title: "Agents",
      text: "Jobs Nova does on its own, once or on a schedule, like a morning brief. Set one up there, or just ask Nova in chat." },
    { target: small ? null : ".p-nav .p-item[aria-label=Settings]", title: "Settings",
      text: IS_REMOTE ? "Voice, looks, models, and Remote: how this phone connects to your computer."
        : "Voice, looks, models and more. Remote puts Nova on your phone, free." },
    { target: null, title: "Stopping Nova",
      text: `If Nova is ever doing something you didn't want, press ${STOP_KEY} or throw your mouse into a screen corner. Everything stops.` },
  ];
}

export default function Tour({ onClose }) {
  const steps = tourSteps(); // per render: follows the window between phone and desktop sizes
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);
  const step = steps[i];

  useLayoutEffect(() => {
    const measure = () => {
      const el = step.target ? document.querySelector(step.target) : null;
      const r = el?.getBoundingClientRect();
      setRect(r && r.width > 0 && r.height > 0 ? { x: r.x, y: r.y, w: r.width, h: r.height } : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [i, step.target]);

  const next = () => (i + 1 < steps.length ? setI(i + 1) : onClose());
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" || e.key === "Enter") next();
      if (e.key === "ArrowLeft") setI((n) => Math.max(0, n - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const pad = 8;
  const hole = rect && { left: rect.x - pad, top: rect.y - pad, width: rect.w + pad * 2, height: rect.h + pad * 2 };
  // The card goes below the spotlight when there's room, above it otherwise.
  const vh = window.innerHeight;
  const vw = window.innerWidth;
  const cardW = Math.min(340, vw - 24);
  let card = { left: (vw - cardW) / 2, top: vh / 2 - 90 };
  if (hole) {
    const below = hole.top + hole.height + 12;
    const top = below + 190 < vh ? below : Math.max(12, hole.top - 12 - 190);
    const left = Math.min(Math.max(12, hole.left + hole.width / 2 - cardW / 2), vw - cardW - 12);
    card = { left, top };
  }

  return (
    <Overlay>
      <div className="p-tour" role="dialog" aria-modal="true" aria-label="Tour of Nova">
        {hole ? <div className="p-tour-hole" style={hole} /> : <div className="p-tour-dim" />}
        <div className="p-tour-card" style={{ ...card, width: cardW }}>
          <div className="n">{i + 1} of {steps.length}</div>
          <b>{step.title}</b>
          <p>{step.text}</p>
          <div className="p-acts">
            <button className="p-link" onClick={onClose}>Skip the tour</button>
            <span className="sp" />
            {i > 0 && <button className="p-sm" onClick={() => setI(i - 1)}>Back</button>}
            <button className="p-sm dark" autoFocus onClick={next}>{i + 1 < steps.length ? "Next" : "Done"}{i + 1 < steps.length && <Icon name="chev" size={13} />}</button>
          </div>
        </div>
      </div>
    </Overlay>
  );
}

/** "Want a quick tour?" -- once, after onboarding. Either answer is final. */
export function TourOffer({ onTake, onLater }) {
  return (
    <Overlay>
      <div className="p-scrim p-sheet-scrim" style={{ zIndex: 65 }}>
        <div className="p-sheet p-askses" role="dialog" aria-modal="true" aria-labelledby="p-tour-offer">
          <h2 id="p-tour-offer">Want a quick tour?</h2>
          <p>A minute or so: where everything is, and the little things, like tapping Nova to make it stop talking.</p>
          <div className="p-acts">
            <button className="p-sm" onClick={onLater}>Not now</button>
            <button className="p-sm dark" autoFocus onClick={onTake}>Show me around</button>
          </div>
          <p className="note">{phone() ? "You can take it any time: Menu, then Take the tour." : "You can take it any time from the search box: type \"tour\"."}</p>
        </div>
      </div>
    </Overlay>
  );
}
