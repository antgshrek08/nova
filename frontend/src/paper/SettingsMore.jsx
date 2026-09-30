// Settings: Notifications, Nova on your phone, and how Nova uses the calendar.
import { useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";
import { Row, Switch } from "./SettingsSections.jsx";
import { useUi } from "./ui.jsx";

function Section({ title, desc, children, aside }) {
  return (
    <div className="p-sgroup">
      <div className="p-shead"><h4>{title}</h4>{aside}</div>
      {desc && <p className="d">{desc}</p>}
      {children}
    </div>
  );
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function NotificationsSection({ prefs }) {
  const ui = useUi();
  const s = prefs.settings;
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  const [devices, setDevices] = useState(null);
  const [quiet, setQuiet] = useState(() => (s.quiet_hours || "22:00-07:00").split("-"));
  useEffect(() => {
    fetch(`${BACKEND_URL}/push/devices`).then((r) => r.json()).then((d) => setDevices(Array.isArray(d) ? d : [])).catch(() => setDevices([]));
  }, []);
  const on = (k, d = true) => (s[k] === undefined ? d : s[k] === true || s[k] === "1");
  const kinds = [
    ["notify_replies", "Nova finished a reply", "When Nova's window isn't in front"],
    ["notify_tasks", "Team jobs", "A Workspace job finished or hit a problem"],
    ["notify_homework", "New homework", "Nova found new assignments on your platforms"],
    ["notify_reminders", "Due tomorrow", "Each evening, what's due the next day"],
    ["notify_needs_you", "Nova needs you", "An action waiting for your OK, or a sign-in"],
  ];
  async function test() {
    if (perm === "default" && typeof Notification !== "undefined") setPerm(await Notification.requestPermission());
    const r = await fetch(`${BACKEND_URL}/notifications/test`, { method: "POST" }).then((x) => x.json()).catch(() => ({}));
    ui.toast(r.pushed ? `Sent. It shows here and on ${plural(r.pushed, "phone")}.` : "Sent here. No phone is set up for notifications yet.");
  }
  const quietOn = Boolean(s.quiet_hours);
  const saveQuiet = (a, b) => { setQuiet([a, b]); prefs.save({ quiet_hours: `${a}-${b}` }); };
  return (
    <>
      <Section title="Notifications" desc="Nova tells you when something happens, on this computer and on your phone."
        aside={<button className="p-sm" onClick={test}><Icon name="bell" />Send a test</button>}>
        {kinds.map(([key, label, desc]) => (
          <Row key={key} label={label} desc={desc}><Switch on={on(key)} label={label} onChange={(v) => prefs.save({ [key]: v })} /></Row>
        ))}
      </Section>
      <Section title="Where they show up">
        <Row label="On this computer" desc={perm === "denied" ? "Windows is blocking them. Turn Nova's notifications on in Windows Settings, Notifications." : "A Windows notification when Nova's window isn't in front"}>
          <Switch on={on("notify_desktop")} label="Notifications on this computer"
            onChange={(v) => { prefs.save({ notify_desktop: v }); if (v && perm === "default") Notification.requestPermission().then(setPerm); }} />
        </Row>
        <Row label="On your phone" desc={devices === null ? "Checking…" : devices.length ? `${plural(devices.length, "phone")} set up` : "No phone set up yet. See Remote."}>
          <Switch on={on("notify_phone")} label="Notifications on your phone" onChange={(v) => prefs.save({ notify_phone: v })} />
        </Row>
        <Row label="Send replies to the phone too" desc="Off keeps your phone for the things that matter">
          <Switch on={on("notify_phone_replies", false)} label="Send replies to the phone" onChange={(v) => prefs.save({ notify_phone_replies: v })} />
        </Row>
        <Row label="Quiet hours" desc={quietOn ? "Nothing reaches your phone then, unless Nova needs you" : "Off"}>
          {quietOn && (
            <>
              <input className="p-input" type="time" value={quiet[0]} onChange={(e) => saveQuiet(e.target.value, quiet[1])} aria-label="Quiet from" style={{ width: 120 }} />
              <span className="note">to</span>
              <input className="p-input" type="time" value={quiet[1]} onChange={(e) => saveQuiet(quiet[0], e.target.value)} aria-label="Quiet until" style={{ width: 120 }} />
            </>
          )}
          <Switch on={quietOn} label="Quiet hours" onChange={(v) => prefs.save({ quiet_hours: v ? `${quiet[0]}-${quiet[1]}` : "" })} />
        </Row>
      </Section>
    </>
  );
}

