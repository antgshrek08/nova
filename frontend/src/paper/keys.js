// Keyboard shortcut labels for the system Nova is running on. The handlers
// accept Ctrl and Cmd alike; only what the user reads changes (⌘ on a Mac).
const agent = typeof navigator === "undefined" ? "" : `${navigator.platform || ""} ${navigator.userAgent || ""}`;
export const IS_MAC = /Mac|iPhone|iPad/.test(agent);
export const IS_WINDOWS = /Win/.test(agent);

export function keys(label) {
  if (!IS_MAC) return label;
  return label
    .replace(/Ctrl\+click/g, "⌘-click")
    .replace(/Ctrl\/Shift\+click/g, "⌘/Shift-click")
    .replace(/Ctrl\+/g, "⌘")
    .replace(/Alt\+/g, "⌥")
    .replace(/Shift\+/g, "⇧");
}
