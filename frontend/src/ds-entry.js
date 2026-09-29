// Barrel entry for design-system sync (claude.ai/design).
// This repo ships as an Electron app, not a published component library, so
// there is no dist/ build to point the converter at. This file plays that
// role: a plain named-export list of the app's real components, exactly as
// a published package's index would look. Not consumed by the app itself.
export { default as AgentWorkspace } from "./components/AgentWorkspace.jsx";
export { default as ChatWindow } from "./components/ChatWindow.jsx";
export { default as ConversationList } from "./components/ConversationList.jsx";
export { default as MemoryPanel } from "./components/MemoryPanel.jsx";
export { default as MessageBubble } from "./components/MessageBubble.jsx";
export { default as ProjectList } from "./components/ProjectList.jsx";
export { default as ProjectPanel } from "./components/ProjectPanel.jsx";
export { default as SettingsModal } from "./components/SettingsModal.jsx";
export { default as SpendMeter } from "./components/SpendMeter.jsx";
export { default as TabBar } from "./components/TabBar.jsx";
