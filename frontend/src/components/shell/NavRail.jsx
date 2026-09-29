// Primary navigation for the redesigned shell (task: "Navigation for Chat,
// Code, Workspace, Memory, and Settings"). One five-item icon rail so all
// five destinations read as peers. Layout is deliberately unchanged since
// Milestone 2 ("preserve the approved left navigation"): Memory stays in
// its existing bottom-cluster slot next to Settings, it just now behaves
// like a real destination (onChangeTab("memory"), active-highlighted) the
// same way Chat/Code/Workspace do, instead of opening a modal. Settings is
// still an overlay -- its own screen redesign is a later milestone.
// Canvas is no longer a peer destination: it is a mode inside Workspace,
// which is already the agent surface -- Workspace is "tell the director and
// watch", Canvas is the same work wired by hand. Two rail items for one idea
// cost a slot and made neither read as the obvious place to go. School takes
// the freed slot: it is the only destination about the user's week rather than
// about Nova's own machinery, and it is the one he opens daily.
// `phone: false` means the destination is desktop-only. Code is an editor and
// Workspace is a node canvas -- neither survives a 375px screen in any honest
// sense, and offering them on a phone only buys a tap that leads somewhere
// unusable. Chat and School are the two the user actually wants on the phone,
// so on a phone they are what the bar shows; nothing is removed from the
import NovaLogo from "../NovaLogo.jsx";

const DESTINATIONS = [
  { id: "chat", label: "Chat", icon: ChatIcon, phone: true },
  { id: "school", label: "Academics", icon: SchoolIcon, phone: true },
  { id: "code", label: "Studio", icon: CodeIcon, phone: false },
  { id: "work", label: "Agents", icon: WorkspaceIcon, phone: false },
];

export default function NavRail({ active, onChangeTab, onOpenSettings, onOpenMiniplayer, customTabs = [], onAddCustomTab }) {
  return (
    <nav
      aria-label="Primary"
      className="flex shrink-0 items-center gap-1 overflow-x-auto border-t border-[#1C202E] bg-[#0E1118] px-2 py-1 sm:w-[64px] sm:flex-col sm:gap-0 sm:overflow-visible sm:border-r sm:border-t-0 sm:px-0 sm:py-3.5"
    >
      <div
        className="mb-4 hidden sm:flex cursor-pointer transition-transform hover:scale-105"
        onClick={() => onChangeTab("chat")}
        title="Nova"
      >
        <NovaLogo size={32} />
      </div>

      <div className="flex flex-1 items-center justify-around gap-1.5 sm:flex-col sm:justify-start">
        {DESTINATIONS.map((d) => (
          <RailButton
            key={d.id}
            label={d.label}
            active={active === d.id}
            onClick={() => onChangeTab(d.id)}
            Icon={d.icon}
            className={d.phone ? "" : "hidden sm:flex"}
          />
        ))}

        {/* Dynamic Custom Tabs */}
        {customTabs.map((ct) => (
          <RailButton
            key={ct.id}
            label={ct.title.slice(0, 7)}
            active={active === ct.id}
            onClick={() => onChangeTab(ct.id)}
            Icon={() => <span className="text-xs">✨</span>}
            className="hidden sm:flex"
          />
        ))}

        {onAddCustomTab && (
          <button
            onClick={onAddCustomTab}
            title="Design & Add Custom Tab with Nova"
            className="group hidden sm:flex w-[52px] shrink-0 flex-col items-center gap-0.5 rounded-xl px-1 py-1.5 transition-all text-[#64748B] hover:bg-[#161B28] hover:text-[#38BDF8]"
          >
            <span className="text-sm leading-none">+</span>
            <span className="text-[9px] font-medium leading-none">Add Tab</span>
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 border-l border-[#1C202E] pl-2 sm:flex-col sm:border-l-0 sm:border-t sm:pl-0 sm:pt-2">
        <RailButton label="Settings" onClick={onOpenSettings} Icon={SettingsIcon} />
        {onOpenMiniplayer && (
          <RailButton label="Mini player" onClick={onOpenMiniplayer} Icon={PictureInPictureIcon} />
        )}
      </div>
    </nav>
  );
}

function RailButton({ label, active, onClick, Icon, className = "" }) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-current={active ? "page" : undefined}
      style={active ? { backgroundColor: "var(--accent-subtle)", color: "var(--accent)", border: "1px solid var(--accent-border)" } : {}}
      className={`${className} group flex w-[50px] shrink-0 flex-col items-center gap-1 rounded-xl px-1 py-2 transition-all sm:w-[52px] ${
        active
          ? "font-semibold shadow-sm"
          : "text-[#94A3B8] hover:bg-[#161B28] hover:text-white"
      }`}
    >
      <Icon />
      <span className="text-[10px] font-medium leading-none tracking-normal">{label}</span>
    </button>
  );
}

function ChatIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}

function CodeIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  );
}

function WorkspaceIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="5" r="2.2" />
      <circle cx="5" cy="19" r="2.2" />
      <circle cx="19" cy="19" r="2.2" />
      <path d="M12 7.2v5M12 12.2 6.4 17M12 12.2 17.6 17" />
    </svg>
  );
}

function SchoolIcon() {
  // A mortarboard: the one destination that is about the user's week rather
  // than about Nova's own machinery, so it should not look like the others.
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4 2.5 9 12 14l9.5-5L12 4Z" />
      <path d="M6.5 11.3V16c0 1.4 2.5 2.6 5.5 2.6s5.5-1.2 5.5-2.6v-4.7" />
      <path d="M21.5 9v5" />
    </svg>
  );
}


function MemoryIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="4" width="7" height="7" rx="1" />
      <rect x="13" y="4" width="7" height="7" rx="1" />
      <rect x="4" y="13" width="7" height="7" rx="1" />
      <rect x="13" y="13" width="7" height="7" rx="1" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function PictureInPictureIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <rect x="12" y="12" width="7" height="5" rx="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
