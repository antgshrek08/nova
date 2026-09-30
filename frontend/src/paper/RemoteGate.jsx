// What the phone shows where a live session with the computer is needed:
// the Remote tab before it's set up or while the computer's Nova is closed,
// and the one-line popup for any feature that needs it.
import Icon from "./icons.jsx";
import Reactor from "./Reactor.jsx";
import { Overlay } from "./ui.jsx";
import { agoText, checkSession, closeAsk, useSession } from "./remote.js";

export default function RemoteGate({ palette, dark, onSetup, onGo }) {
  const s = useSession();
  if (!s.configured) {
    return (
      <section className="p-page p-gate" aria-label="Remote">
        <div className="p-gate-in">
          <div className="r"><Reactor palette={palette} dark={dark} state="idle" /></div>
          <h1>Set up Remote</h1>
          <p>Talk to Nova on your computer from here, like a remote session. On your computer, open <b>Settings, Remote</b>, add this device, and scan its code with this phone.</p>
          <button className="p-btn dark" onClick={onSetup}>How to set it up</button>
        </div>
      </section>
    );
  }
  return (
    <section className="p-page p-gate" aria-label="Remote">
      <div className="p-gate-in">
        <div className="r"><Reactor palette={palette} dark={dark} state={s.checking ? "thinking" : "idle"} /></div>
        <h1>{s.checking ? "Looking for your Nova…" : "Your Nova isn't open"}</h1>
        <p>Open Nova on {s.name || "your computer"} and leave it running. Tailscale needs to be on here and there.</p>
        <button className="p-btn dark" disabled={s.checking} onClick={checkSession}><Icon name="search" size={15} />{s.checking ? "Searching…" : "Search for open Nova sessions"}</button>
        {s.checkedAt > 0 && !s.checking && <p className="note">Checked {agoText(s.checkedAt)}.</p>}
        <div className="p-gate-links">
          <span className="note">Still here without it:</span>
          <button className="p-chip" onClick={() => onGo("memory")}>Memory</button>
          <button className="p-chip" onClick={() => onGo("academics")}>Academics</button>
          <button className="p-chip" onClick={() => onGo("agents")}>Agents</button>
          <button className="p-chip" onClick={() => onGo("studio")}>Studio</button>
        </div>
      </div>
    </section>
  );
}

/** "This needs an active Nova session" -- shown by requireLive(). */
export function SessionAsk() {
  const s = useSession();
  if (!s.asking) return null;
  const found = s.live;
  return (
    <Overlay>
    <div className="p-scrim p-sheet-scrim" style={{ zIndex: 70 }} onPointerDown={(e) => { if (e.target === e.currentTarget) closeAsk(); }}>
      <div className="p-sheet p-askses" role="alertdialog" aria-modal="true" aria-labelledby="p-askses-t">
        <h2 id="p-askses-t">{found ? "Found your Nova" : "Needs an active Nova session"}</h2>
        <p>{found ? "It's open now. Try again."
          : `${s.asking.what} runs on your computer. Open Nova on ${s.name || "your computer"}, keep it running, and try again.`}</p>
        <div className="p-acts">
          {!found && <button className="p-sm" disabled={s.checking} onClick={checkSession}>{s.checking ? "Searching…" : "Search again"}</button>}
          <button className="p-sm dark" onClick={closeAsk}>OK</button>
        </div>
      </div>
    </div>
    </Overlay>
  );
}
