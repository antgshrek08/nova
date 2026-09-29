// Add tab (the user asks Nova to build one) and the user's own tabs.
import { useState } from "react";
import Icon from "./icons.jsx";
import Guide, { GuideButton } from "./Guide.jsx";
import Reactor from "./Reactor.jsx";

const IDEAS = [
  ["Grade calculator", "What you need on the final, from your real grades"],
  ["Flashcards", "Decks made from your notes and readings"],
  ["Focus timer", "Work sessions that pause Nova's notifications"],
  ["Graphing", "Plot functions from your calculus homework"],
  ["Reading list", "Everything assigned, with what's left to read"],
];

function buildPrompt(what) {
  return `Build me a new tab in Nova: ${what}. Ask me anything you need to know first. `
    + "Then build it as a custom tab, test it, and tell me when it's ready to use.";
}

export function AddTabView({ palette, dark, onAsk, models, minModels = 4, onModels }) {
  const [text, setText] = useState("");
  const ask = (what) => { if (what.trim()) onAsk(buildPrompt(what.trim())); };
  return (
    <section className="p-page" aria-label="Add a tab">
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} />
        <div><h1>Add a tab</h1><div className="sub">Tell Nova what you want. It asks what it needs, builds the tab, tests it, and adds it here.</div></div>
        <GuideButton id="addtab" />
      </div>
      <div className="scroll p-pg p-add">
        <Guide id="addtab" />
        <form className="p-ask" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Describe a tab: a grade calculator for my courses" aria-label="Describe a tab" />
          <button className="p-send" type="submit" disabled={!text.trim()} aria-label="Ask Nova to build it"><Icon name="arrow" /></button>
        </form>
        <div className="muted">Or start from an idea</div>
        <div className="p-ideas">
          {IDEAS.map(([name, note]) => (
            <button className="p-idea" key={name} onClick={() => ask(`a ${name.toLowerCase()} tab (${note.toLowerCase()})`)}>
              <b>{name}</b><span>{note}</span><em>Build with Nova</em>
            </button>
          ))}
          <button className="p-idea" onClick={() => document.querySelector(".p-ask input")?.focus()}>
            <b>Something else</b><span>Describe anything, and Nova asks what it needs</span><em>Describe it</em>
          </button>
        </div>
        <p className="note">Nova builds in a conversation, so you can watch each step, answer its questions, and stop it any time.</p>
        {models && !models.unlocked && models.count != null && (
          <div className="p-lock">
            <div style={{ flex: 1 }}>
              <b style={{ fontWeight: 500 }}>Workspace</b>
              <div className="note">A team of your models working together. It appears in the sidebar once {minModels} models are ready ({models.count} of {minModels}).</div>
              <div className="bar"><i style={{ width: `${Math.min(100, (models.count / minModels) * 100)}%` }} /></div>
            </div>
            <button className="p-sm" onClick={onModels}>Add models</button>
          </div>
        )}
      </div>
    </section>
  );
}

export function UserTabView({ tab, palette, dark, onRemove, onAsk }) {
  if (!tab) return null;
  return (
    <section className="p-page" aria-label={tab.title}>
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} />
        <div><h1>{tab.title}</h1><div className="sub">{tab.description || "Built by Nova for you"}</div></div>
        <span className="sp" />
        <button className="p-sm" onClick={() => onAsk(`Change my "${tab.title}" tab: `)}>Ask Nova to change it</button>
        <button className="p-sm danger" onClick={() => onRemove(tab)} title="Remove this tab (you can undo)"><Icon name="trash" />Remove tab</button>
      </div>
      <div className="p-pg" style={{ minHeight: 0 }}>
        <iframe className="p-frame" title={tab.title} sandbox="allow-scripts allow-forms" srcDoc={tab.html_content || "<p>This tab has no content yet.</p>"} />
      </div>
    </section>
  );
}
