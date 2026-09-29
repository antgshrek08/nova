const TABS = [
  { id: "chat", label: "Chat" },
  { id: "code", label: "Code" },
  { id: "work", label: "Workspace" },
];

export default function TabBar({ active, onChange }) {
  return (
    <div className="flex gap-1 p-2">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
            active === tab.id
              ? "bg-indigo-600 text-white"
              : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
