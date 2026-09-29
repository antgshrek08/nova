// Beginner help on each main screen: what it's for and how to use it, shown
// until the user says they've got it, and back any time from the screen's
// "How this works" button. What each screen says lives in GUIDES below.
import Icon from "./icons.jsx";
import { undismiss, useDismissed } from "./dismissals.js";
import { IS_TOUCH, keys, tap } from "./keys.js";

export const GUIDES = {
  chat: {
    title: "How to talk to Nova",
    points: [
      ["chat", "Type or speak (the microphone) anything: a question, or something to do. Nova picks the best model for it."],
      ["bolt", "Nova can act, not just answer: open websites, work in apps, read your files, do homework. It asks first unless you changed that in Settings, Autonomy."],
      ["stop", "The send button turns into Stop while Nova works. Press it, or Esc, to stop."],
      ["brain", "Nova remembers what matters about you between chats. See and correct it in Memory."],
    ],
    tries: ["What's due this week?", "Summarize this PDF for me", "Plan study time for my next test", "Open my Canvas and check my grades"],
  },
  academics: {
    title: "Your school work in one place",
    points: [
      ["cap", "Everything due from Canvas and your other homework sites, grouped by day. Connect them in Settings, Canvas and Homework platforms."],
      ["cal", "Calendar shows your classes and events next to due dates, finds free time, and plans study sessions."],
      ["bolt", tap("Right-click an assignment to ask Nova to do it or explain it. Autopilot shows homework Nova is working through.")],
      ["refresh", "Sync pulls the newest assignments now; Nova also syncs every night."],
    ],
  },
  studio: {
    title: "Build things with Nova",
    points: [
      ["folder", "Open a project folder with the name at the top left, or start in the sandbox."],
      ["chat", "Ask Nova on the right to write, fix or explain code. Its changes appear under Changes, so you can review each one."],
      ["term", keys("The bottom panel has a terminal, Git, a live preview of your app, and Ship to put it online. Ctrl+J shows it.")],
      ["keys", keys("Ctrl+S saves, Ctrl+W closes a file, Ctrl+L shows or hides Nova.")],
    ],
  },
  agents: {
    title: "See what Nova is doing",
    points: [
      ["nodes", "Every task Nova is working on, step by step, with what each step did."],
      ["stop", "Stop everything halts Nova at once, anywhere. Nothing else happens until you press Resume."],
      ["team", "Jobs from Workspace show here too, so you can follow the whole team."],
    ],
  },
  memory: {
    title: "What Nova knows about you",
    points: [
      ["brain", "Nova learns facts and preferences from your chats and uses them every time you talk."],
      ["edit", IS_TOUCH ? "Wrong? Tap Edit to fix it. Not wanted? Tap Forget. You can undo." : "Wrong? Double-click to fix it. Not wanted? Select it and press Forget. You can undo."],
      ["file", "Connect your Obsidian notes in Settings, Notes, and Nova reads those too. Everything stays on this computer."],
    ],
  },
  workspace: {
    title: "Your models as a team",
    points: [
      ["team", "Describe a whole job. A director plans it and hands each step to the model that's best at it."],
      ["sliders", "Your team shows which model does each role. The recommended picks are marked; change any of them."],
      ["nodes", "Follow each job here or in Agents, and stop it any time."],
    ],
  },
  addtab: {
    title: "Make Nova your own",
    points: [
      ["plus", "Describe a tab you wish Nova had: a grade calculator, flashcards, a focus timer. Nova builds it in a chat and adds it to the sidebar."],
      ["chat", "You can watch it work, answer its questions, and ask for changes later from the tab itself."],
    ],
  },
};

/** The card. Shows until "Got it" is pressed, then never again, on any
 * device, until the screen's "How this works" button brings it back. */
export default function Guide({ id, onTry }) {
  const g = GUIDES[id];
  const [dismissed, dismiss] = useDismissed(`guide.${id}`);
  if (!g || dismissed !== false) return null; // null: not known yet -- no flash
  return (
    <section className="p-guide" aria-label={g.title}>
      <div className="hd"><b>{g.title}</b><button className="p-link" onClick={dismiss} aria-label="Hide this guide">Got it</button></div>
      <ul>{g.points.map(([icon, text]) => <li key={text}><Icon name={icon} size={15} /><span>{text}</span></li>)}</ul>
      {g.tries && onTry && (
        <div className="tries"><span className="note">Try:</span>{g.tries.map((t) => <button key={t} className="p-chip" onClick={() => onTry(t)}>{t}</button>)}</div>
      )}
    </section>
  );
}

/** The screen header's "How this works" button. */
export function GuideButton({ id }) {
  return (
    <button className="p-ib plain p-guidebtn" title="How this works" aria-label="How this works"
      onClick={() => undismiss(`guide.${id}`)}>
      <Icon name="info" size={16} />
    </button>
  );
}
