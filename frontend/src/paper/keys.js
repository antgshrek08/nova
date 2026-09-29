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

// Phones and tablets: no right-click; menus open with press and hold instead
// (see UiProvider's long-press in ui.jsx).
export const IS_TOUCH = typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;

export function tap(label) {
  return IS_TOUCH ? label.replace(/Right-click/g, "Press and hold").replace(/right-click/g, "press and hold") : label;
}
