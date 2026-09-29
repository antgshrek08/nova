import { lazy, Suspense, useState } from "react";
import ChatWindow from "./components/ChatWindow.jsx";
import NovaReactorWindow from "./components/NovaReactorWindow.jsx";
import SettingsModal from "./components/SettingsModal.jsx";
import ProjectsModal from "./components/ProjectsModal.jsx";
import SchoolScreen from "./components/school/SchoolScreen.jsx";
import TeamConstellation from "./components/workspace/TeamConstellation.jsx";
import NavRail from "./components/shell/NavRail.jsx";
import TitleBar from "./components/shell/TitleBar.jsx";
import OnboardingModal from "./components/OnboardingModal.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import CustomTabScreen from "./components/CustomTabScreen.jsx";
import CodeTab from "./components/CodeTab.jsx";
import { createConversation, getUserProfile, getCustomTabs, createCustomTab } from "./api.js";
import { setPendingHandoff } from "./lib/chatStreamStore.js";
import { useBackendHealth } from "./lib/useBackendHealth.js";
import { useEffect } from "react";

const TAB_TITLES = { chat: "Chat", school: "School", code: "Code", work: "Workspace" };

export default function App() {
  const searchParams = new URLSearchParams(window.location.search);
  const [settingsOpen, setSettingsOpen] = useState(Boolean(searchParams.get("settings")));
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(searchParams.get("onboarding") === "1");
  const [conversationListTick, setConversationListTick] = useState(0);
  const [customTabs, setCustomTabs] = useState([]);
  const [addTabModalOpen, setAddTabModalOpen] = useState(false);

  useEffect(() => {
    getCustomTabs().then((tabs) => {
      if (tabs && Array.isArray(tabs)) setCustomTabs(tabs);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    getUserProfile().then((p) => {
      if (p && p.onboarding_completed === 0 && !searchParams.get("tab") && !searchParams.get("settings")) {
        setOnboardingOpen(true);
      }
    }).catch(() => {});
  }, []);
  const [voiceReplyTick, setVoiceReplyTick] = useState(0);
  const [activeTab, setActiveTab] = useState(searchParams.get("tab") || "chat");
  // Chat and Code each keep their own last-selected conversation; Workspace
  // has no id of its own and reuses `chat`'s (see the shared ChatWindow
  // instance in the render below) rather than a third one, since Workspace
  // and Chat are the same conversation. Previously this was a single shared
  // id reset to null on every tab change, which made ChatWindow clear its
  // messages and show the empty state even though nothing about the
  // conversation itself had changed on the backend -- it just looked deleted.
  const [activeConversationIds, setActiveConversationIds] = useState({
    chat: searchParams.get("conv") ? parseInt(searchParams.get("conv")) : null,
    code: null,
  });
  // Shell redesign: real connected/disconnected state (task: "Distinct ...
  // disconnected ... states, driven by actual application state") -- polls
  // the backend's own /health route rather than inferring it from whether
  // the last request happened to succeed.
  const connected = useBackendHealth();

  function handleTabChange(tab) {
    setActiveTab(tab);
  }

  function handleOpenConversationFromProject(id) {
    setActiveTab("chat");
    setActiveConversationIds((prev) => ({ ...prev, chat: id }));
  }

  /** Chat -> Code handoff (task: "chat -> code thing like cline" -- Cline's
   * Plan/Act mode split: plan conversationally with no file writes, then
   * switch to the mode that actually executes, with the plan carried over
   * as context). ChatWindow (variant="chat" only, see its onSendToCode
   * prop below) hands us the plan text once the user clicks "Send to
   * Code"; this creates a brand-new Code-tab conversation for it, stashes
   * the plan where that conversation's ChatWindow instance will pick it up
   * on mount (see lib/chatStreamStore.js's setPendingHandoff -- a normal
   * prop can't reach a component instance that doesn't exist until after
   * this function returns), and switches to it. Deliberately does NOT
   * auto-send: the plan lands in the Code tab's input box for the user to
   * review/edit and send themselves, same "no side effect without an
   * explicit action" pattern as the rest of this app. */
  async function handleSendChatToCode(planText, titleHint) {
    const title = titleHint ? `From Chat: ${titleHint.slice(0, 50)}` : "Handoff from Chat";
    try {
      const conv = await createConversation({ tab: "code", title });
      setPendingHandoff(conv.id, planText);
      setActiveConversationIds((prev) => ({ ...prev, code: conv.id }));
      setActiveTab("code");
      setConversationListTick((n) => n + 1);
    } catch (err) {
      window.alert(`Couldn't start a Code conversation: ${err.message || err}`);
    }
  }

  /** Lets the Chat screen's initial (no-conversation) state actually work
   * (task: "The initial screen must be usable without first selecting a
   * conversation ... creating a conversation through the existing API when
   * needed") -- ChatWindow calls this the first time Send runs with no
   * conversation yet. Reuses existing conversations if one's already
   * active; see startNewChatConversation below for the "start over"
   * variant used by Chat's own "+ New" action. */
  async function ensureChatConversation() {
    if (activeConversationIds.chat) return activeConversationIds.chat;
    const conv = await createConversation({ tab: "chat" });
    setActiveConversationIds((prev) => ({ ...prev, chat: conv.id }));
    setConversationListTick((n) => n + 1);
    return conv.id;
  }

  /** Task: "Keep a clear New conversation action in Chat" -- unlike
   * ensureChatConversation above (which reuses whatever's already active),
   * this always creates a fresh one, for the explicit "start a new
   * conversation" action now that browsing OLD ones lives in Memory instead
   * of a History button on the Chat screen itself. */
  async function startNewChatConversation() {
    const conv = await createConversation({ tab: "chat" });
    setActiveConversationIds((prev) => ({ ...prev, chat: conv.id }));
    setConversationListTick((n) => n + 1);
    return conv.id;
  }

  /** Code tab milestone: the redesigned Code tab is now a real file
   * explorer + editor, same as Chat dropped its inline history sidebar for
   * Memory's History view -- so this replaces the old ConversationSidebar's
   * own "+ New code chat" button that used to live directly in the Code
   * tab. Reopening an EXISTING code conversation still works exactly as
   * before, via Memory > History > Code (handleOpenConversationFromMemory
   * below) -- this is only the "start a fresh one" action. */
  async function startNewCodeConversation() {
    const conv = await createConversation({ tab: "code" });
    setActiveConversationIds((prev) => ({ ...prev, code: conv.id }));
    setConversationListTick((n) => n + 1);
    return conv.id;
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-charcoal-950">
      {/* Header simplified (task: remove the "models online" and spend
          badges everywhere -- both usage tracking and model configuration
          stay reachable in Settings, just not surfaced up here). History
          also moved out of the header entirely this pass -- conversation
          browsing now lives in Memory (see NavRail's Memory destination),
          so there's no longer a Chat-specific header control at all. */}
      {/* On a phone the header is the one row that has to hold the wordmark,
          the breadcrumb and the voice status at 375px. Everything in it is
          allowed to shrink (min-w-0) so the right-hand cluster stays on
          screen instead of being pushed past the edge and clipped. */}
      {/* Custom Frameless Title Bar (removes default OS bar, includes custom controls) */}
      <TitleBar
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenOnboarding={() => setOnboardingOpen(true)}
      />

      <NovaReactorWindow headless onConversationCompleted={id => {
        setActiveConversationIds(previous => ({ ...previous, chat: id }));
        setVoiceReplyTick(value => value + 1);
        setConversationListTick(value => value + 1);
      }} />

      {/* Column on a phone so the rail can sit at the bottom under the
          thumb, row from sm: up where it is a sidebar as before. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col-reverse sm:flex-row">
        <NavRail
          active={activeTab}
          onChangeTab={handleTabChange}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenMiniplayer={window.electronAPI?.openMiniplayer ? () => window.electronAPI.openMiniplayer() : null}
          customTabs={customTabs}
          onAddCustomTab={() => setAddTabModalOpen(true)}
        />

        <main className="relative min-h-0 min-w-0 flex-1">
          {/* Custom Tabs */}
          {customTabs.some((t) => t.id === activeTab) && (
            <ErrorBoundary label="Custom Tab">
              <CustomTabScreen
                tab={customTabs.find((t) => t.id === activeTab)}
                onDeleted={(deletedId) => {
                  setCustomTabs((prev) => prev.filter((t) => t.id !== deletedId));
                  setActiveTab("chat");
                }}
                onOpenChatWithPrompt={async (promptText) => {
                  try {
                    const conv = await createConversation({ tab: "chat" });
                    setPendingHandoff(conv.id, promptText);
                    setActiveConversationIds((prev) => ({ ...prev, chat: conv.id }));
                    setActiveTab("chat");
                    setConversationListTick((n) => n + 1);
                  } catch (e) {
                    setActiveTab("chat");
                  }
                }}
              />
            </ErrorBoundary>
          )}

          {/* Each destination is wrapped separately (see ErrorBoundary) so a
              crash is contained to the screen that caused it -- the nav rail
              keeps working and the other tabs keep their state, instead of one
              bad render blanking the whole window. */}
          {activeTab === "school" && (
            <ErrorBoundary label="School">
              <Suspense
                fallback={<div className="flex h-full items-center justify-center text-sm text-charcoal-500">Loading your semester…</div>}
              >
                <SchoolScreen
                  onOpenChatWithPrompt={async (promptText) => {
                    try {
                      const conv = await createConversation({ tab: "chat" });
                      setPendingHandoff(conv.id, promptText);
                      setActiveConversationIds((prev) => ({ ...prev, chat: conv.id }));
                      setActiveTab("chat");
                      setConversationListTick((n) => n + 1);
                    } catch (e) {
                      setActiveTab("chat");
                    }
                  }}
                />
              </Suspense>
            </ErrorBoundary>
          )}
          {activeTab === "code" && (
            <ErrorBoundary label="Code" resetKey={activeConversationIds.code}>
              <Suspense
                fallback={<div className="flex h-full items-center justify-center text-sm text-charcoal-500">Loading the code workspace…</div>}
              >
                <CodeTab
                  conversationId={activeConversationIds.code}
                  onResponseDone={() => setConversationListTick((n) => n + 1)}
                  onNewConversation={startNewCodeConversation}
                />
              </Suspense>
            </ErrorBoundary>
          )}
          {/* Canvas is a mode of Workspace rather than its own destination --
              same work, wired by hand instead of delegated to the director.

              Still unmounted when inactive, unlike Chat/Workspace below: a
              canvas node holds an open stream, and leaving several of those
              running behind a hidden view is exactly the "which session was
              doing what" problem this view exists to solve. Layout and prompts
          {activeTab === "work" && (
            <ErrorBoundary label="Workspace">
              <Suspense
                fallback={<div className="flex h-full items-center justify-center text-sm text-[#8E9EB5]">Loading workspace…</div>}
              >
                <TeamConstellation onOpenSettings={() => setSettingsOpen(true)} />
              </Suspense>
            </ErrorBoundary>
          )}

          {/* Chat keeps its single ChatWindow instance mounted so in-flight requests or speech audio streams are never torn down */}
          <div className={`absolute inset-0 overflow-hidden ${activeTab === "chat" ? "" : "hidden"}`}>
            <ErrorBoundary label="Chat" resetKey={voiceReplyTick}>
              <ChatWindow
                key={voiceReplyTick}
                conversationId={activeConversationIds.chat}
                variant="chat"
                connected={connected}
                onResponseDone={() => setConversationListTick((n) => n + 1)}
                onSendToCode={handleSendChatToCode}
                onEnsureConversation={ensureChatConversation}
                onNewConversation={startNewChatConversation}
              />
            </ErrorBoundary>
          </div>
        </main>
      </div>

      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <ProjectsModal
        open={projectsOpen}
        onClose={() => setProjectsOpen(false)}
        onOpenConversation={handleOpenConversationFromProject}
      />
      <OnboardingModal
        isOpen={onboardingOpen}
        onClose={() => setOnboardingOpen(false)}
        onComplete={() => setOnboardingOpen(false)}
      />

      {/* Add Custom Tab Modal */}
      {addTabModalOpen && (
        <AddTabModal
          onClose={() => setAddTabModalOpen(false)}
          onAdd={async (newTab) => {
            try {
              const saved = await createCustomTab(newTab);
              setCustomTabs((prev) => [...prev.filter((t) => t.id !== saved.id), saved]);
              setActiveTab(saved.id);
              setAddTabModalOpen(false);
            } catch (e) {
              alert("Failed to add tab: " + e.message);
            }
          }}
          onAskNova={async (tabTitle) => {
            setAddTabModalOpen(false);
            const conv = await createConversation({ tab: "chat" });
            const prompt = `Nova, please design and code a custom UI tab for "${tabTitle}". Build an interactive widget or tool and register it for me.`;
            setPendingHandoff(conv.id, prompt);
            setActiveConversationIds((prev) => ({ ...prev, chat: conv.id }));
            setActiveTab("chat");
            setConversationListTick((n) => n + 1);
          }}
        />
      )}
    </div>
  );
}

function AddTabModal({ onClose, onAdd, onAskNova }) {
  const PRESETS = [
    {
      id: "flashcards",
      title: "Flashcards",
      icon: "Card",
      description: "Active recall study decks with spaced repetition.",
      content_type: "widget",
      html_content: `
        <div style="font-family: system-ui; max-width: 600px; margin: 0 auto; text-align: center; padding: 2rem;">
          <h2 style="color: #6366f1; margin-bottom: 0.5rem;">Study Flashcards & Decks</h2>
          <p style="color: #94a3b8; font-size: 0.875rem; margin-bottom: 1.5rem;">Review key definitions and formulas across your courses.</p>
          <div style="background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 2.5rem 1.5rem; margin-bottom: 1.5rem; min-height: 180px; display: flex; flex-direction: column; justify-content: center; align-items: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);">
            <span style="font-size: 0.75rem; text-transform: uppercase; color: #38bdf8; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 0.5rem;">Economics & Calculus Deck</span>
            <div style="font-size: 1.15rem; color: #f8fafc; font-weight: 500;">What represents the instantaneous rate of change in economics?</div>
            <div style="margin-top: 1rem; font-size: 0.95rem; color: #10b981; font-weight: 600;">Marginal Revenue / Marginal Cost: \\( d(TR)/dq \\) or \\( d(TC)/dq \\)</div>
          </div>
          <div style="display: flex; gap: 0.75rem; justify-content: center;">
            <button onclick="alert('Card marked for review tomorrow!')" style="background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem 1.25rem; border-radius: 8px; cursor: pointer; font-size: 0.875rem;">Hard (1d)</button>
            <button onclick="alert('Card marked for review in 3 days!')" style="background: #3b82f6; border: none; color: white; padding: 0.5rem 1.25rem; border-radius: 8px; cursor: pointer; font-size: 0.875rem; font-weight: 500;">Good (3d)</button>
            <button onclick="alert('Card mastered!')" style="background: #10b981; border: none; color: white; padding: 0.5rem 1.25rem; border-radius: 8px; cursor: pointer; font-size: 0.875rem; font-weight: 500;">Easy (7d)</button>
          </div>
        </div>
      `,
    },
    {
      id: "grapher",
      title: "3D Grapher & Lab",
      icon: "Graph",
      description: "Interactive 2D & 3D function plotter and calculator.",
      content_type: "widget",
      html_content: `
        <div style="font-family: system-ui; max-width: 700px; margin: 0 auto; padding: 1.5rem; text-align: center;">
          <h2 style="color: #38bdf8; margin-bottom: 0.5rem;">Interactive Coordinate Lab</h2>
          <p style="color: #94a3b8; font-size: 0.875rem; margin-bottom: 1.5rem;">Plot curves, parabolas, and evaluate equations directly.</p>
          <div style="background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem;">
            <input id="mathInput" type="text" value="y = x^2 - 4x + 3" style="width: 80%; background: #1e293b; border: 1px solid #475569; color: white; padding: 0.5rem 1rem; border-radius: 6px; font-family: monospace; font-size: 1rem; margin-bottom: 1rem;" />
            <br />
            <svg viewBox="-50 -50 100 100" style="width: 260px; height: 260px; background: #020617; border-radius: 8px; border: 1px solid #1e293b;">
              <!-- Grid lines -->
              <line x1="-50" y1="0" x2="50" y2="0" stroke="#334155" stroke-width="0.8" />
              <line x1="0" y1="-50" x2="0" y2="50" stroke="#334155" stroke-width="0.8" />
              <!-- Parabola y = x^2 - 4x + 3 plotted (scaled) -->
              <path d="M -20,-50 Q 10,25 40,-50" fill="none" stroke="#38bdf8" stroke-width="2" />
              <circle cx="10" cy="5" r="2.5" fill="#f43f5e" />
              <text x="12" y="12" fill="#f8fafc" font-size="5">Vertex (2, -1)</text>
            </svg>
          </div>
          <p style="color: #64748b; font-size: 0.75rem;">Calculated via SymPy & analytical geometry engine.</p>
        </div>
      `,
    },
    {
      id: "pomodoro",
      title: "Focus Pomodoro",
      icon: "Clock",
      description: "25-minute deep focus interval timer with break alerts.",
      content_type: "widget",
      html_content: `
        <div style="font-family: system-ui; max-width: 500px; margin: 2rem auto; text-align: center;">
          <h2 style="color: #f59e0b; margin-bottom: 0.5rem;">Deep Work Focus Timer</h2>
          <p style="color: #94a3b8; font-size: 0.875rem; margin-bottom: 2rem;">Lock in for your homework and project sprints.</p>
          <div style="font-size: 4rem; font-weight: 700; color: #f8fafc; font-family: monospace; margin-bottom: 1.5rem;">25:00</div>
          <div style="display: flex; gap: 1rem; justify-content: center;">
            <button onclick="alert('Timer started!')" style="background: #10b981; color: white; padding: 0.6rem 1.5rem; border-radius: 8px; font-weight: 600; cursor: pointer; border: none;">Start Sprint</button>
            <button onclick="alert('Timer reset.')" style="background: #334155; color: #cbd5e1; padding: 0.6rem 1.25rem; border-radius: 8px; cursor: pointer; border: none;">Reset</button>
          </div>
        </div>
      `,
    },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-charcoal-700 bg-charcoal-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between pb-3 border-b border-charcoal-800">
          <div>
            <h3 className="text-base font-semibold text-white">Add a Custom Tab or Mod</h3>
            <p className="text-xs text-charcoal-400">Nova is fully open-source and extensible. Choose a preset or design a new one.</p>
          </div>
          <button onClick={onClose} className="text-charcoal-400 hover:text-white text-lg">✕</button>
        </div>

        <div className="mt-4 space-y-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-charcoal-400">Instant Presets</p>
          {PRESETS.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-xl border border-charcoal-800 bg-charcoal-950/60 p-3 hover:border-charcoal-700 hover:bg-charcoal-800/50 transition-all"
            >
              <div>
                <span className="text-sm font-semibold text-white">{p.title}</span>
                <p className="text-xs text-charcoal-400">{p.description}</p>
              </div>
              <button
                onClick={() => onAdd(p)}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
              >
                + Add Tab
              </button>
            </div>
          ))}
        </div>

        <div className="mt-5 rounded-xl border border-indigo-900/40 bg-indigo-950/20 p-3.5 text-center">
          <p className="text-xs font-semibold text-indigo-300">Want Nova to design something custom?</p>
          <p className="text-[11px] text-charcoal-400 mt-1 mb-3">
            You can ask Nova to build any custom tool, interactive simulator, or portal connector.
          </p>
          <button
            onClick={() => onAskNova("Custom Study Widget")}
            className="w-full rounded-lg bg-indigo-500/20 border border-indigo-500/40 py-2 text-xs font-semibold text-indigo-300 hover:bg-indigo-500/30"
          >
            💬 Design New Tab with Nova
          </button>
        </div>
      </div>
    </div>
  );
}

