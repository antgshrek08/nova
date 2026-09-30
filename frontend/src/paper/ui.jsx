// Shared interaction pieces for the Paper interface: right-click menus,
// undo toasts, a confirm dialog, multi-select lists and checkboxes. One
// provider (UiProvider) renders the overlays; screens reach them through
// useUi(). Everything here works from the keyboard as well as the mouse.
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "./icons.jsx";
import { keys } from "./keys.js";

const UiContext = createContext(null);
export const useUi = () => useContext(UiContext);

/* ---- context menu ------------------------------------------------------ */

function Menu({ menu, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: menu.x, top: menu.y });

  useLayoutEffect(() => {
    // Keep the whole menu on screen: flip left/up near the edges.
    const el = ref.current;
    const { width, height } = el.getBoundingClientRect();
    const left = menu.x + width > window.innerWidth - 8 ? Math.max(8, menu.x - width) : menu.x;
    const top = menu.y + height > window.innerHeight - 8 ? Math.max(8, menu.y - height) : menu.y;
    setPos({ left, top });
    el.querySelector("[role=menuitem]:not([disabled])")?.focus();
  }, [menu]);

  useEffect(() => {
    const away = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    const close = () => onClose();
    document.addEventListener("pointerdown", away, true);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    // The user scrolling closes it; a page scrolling itself (a chat streaming
    // to the bottom) must not.
    const wheel = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    document.addEventListener("wheel", wheel, { capture: true, passive: true });
    return () => {
      document.removeEventListener("pointerdown", away, true);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
      document.removeEventListener("wheel", wheel, { capture: true });
    };
  }, [onClose]);

  const onKeyDown = (e) => {
    const items = [...ref.current.querySelectorAll("[role=menuitem]:not([disabled])")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Home") { e.preventDefault(); items[0]?.focus(); }
    else if (e.key === "End") { e.preventDefault(); items[items.length - 1]?.focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); onClose(true); }
  };

  return (
    <div ref={ref} className="p-menu" role="menu" aria-label={menu.label || "Actions"} style={pos} onKeyDown={onKeyDown}
      onContextMenu={(e) => e.preventDefault()}>
      {menu.title && <div className="p-menu-title">{menu.title}</div>}
      {menu.items.filter(Boolean).map((item, i) => (item === "-"
        ? <div key={`s${i}`} className="p-menu-sep" role="separator" />
        : (
          <button key={item.label} role="menuitem" className={item.danger ? "danger" : undefined} disabled={item.disabled}
            onClick={() => { onClose(true); item.onSelect?.(); }}>
            {item.icon ? <Icon name={item.icon} size={15} /> : <span className="p-menu-gap" />}
            <span className="l">{item.label}</span>
            {item.shortcut && <kbd>{item.shortcut}</kbd>}
          </button>
        )))}
    </div>
  );
}

/* ---- toasts ------------------------------------------------------------ */

function Toasts({ toasts, dismiss }) {
  return (
    <div className="p-toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`p-toast${t.error ? " error" : ""}`}>
          <span>{t.message}</span>
          {t.action && <button className="p-link strong" onClick={() => { dismiss(t.id); t.action.run(); }}>{t.action.label}</button>}
          <button className="p-link" aria-label="Dismiss" onClick={() => dismiss(t.id, true)}><Icon name="x" size={13} /></button>
        </div>
      ))}
    </div>
  );
}

/* ---- confirm dialog ---------------------------------------------------- */

function Confirm({ ask, onAnswer }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.querySelector("button.p-sm.dark")?.focus(); }, []);
  const onKeyDown = (e) => {
    if (e.key === "Escape") onAnswer(false);
    if (e.key === "Tab") { // keep focus inside the dialog
      const f = [...ref.current.querySelectorAll("button")];
      const i = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length]?.focus();
    }
  };
  return (
    <div className="p-scrim" onPointerDown={(e) => { if (e.target === e.currentTarget) onAnswer(false); }}>
      <div ref={ref} className="p-dialog" role="alertdialog" aria-modal="true" aria-labelledby="p-dialog-t" onKeyDown={onKeyDown}>
        <h2 id="p-dialog-t">{ask.title}</h2>
        {ask.body && <p>{ask.body}</p>}
        <div className="p-acts">
          <button className="p-sm" onClick={() => onAnswer(false)}>{ask.cancel || "Cancel"}</button>
          <button className={`p-sm dark${ask.danger ? " danger" : ""}`} onClick={() => onAnswer(true)}>{ask.confirm || "OK"}</button>
        </div>
      </div>
    </div>
  );
}

/* ---- text fields and selected text get the usual edit menu ------------- */

function editable(el) {
  if (!el) return null;
  if (el.isContentEditable) return el;
  if (el.tagName === "TEXTAREA") return el;
  if (el.tagName === "INPUT" && /^(text|search|url|email|tel|number|password|)$/i.test(el.type)) return el;
  return null;
}

function editMenu(target, askNova) {
  const field = editable(target);
  const selected = String(window.getSelection?.() || "").trim();
  const exec = (cmd) => { field?.focus(); document.execCommand(cmd); };
  const paste = async () => {
    field?.focus();
    try {
      const text = await navigator.clipboard.readText();
      if (text) document.execCommand("insertText", false, text);
    } catch { document.execCommand("paste"); }
  };
  if (field) {
    const hasSel = field.selectionStart !== field.selectionEnd || (field.isContentEditable && selected);
    const secret = field.type === "password";
    return [
      { label: "Undo", shortcut: keys("Ctrl+Z"), onSelect: () => exec("undo") },
      { label: "Redo", shortcut: keys("Ctrl+Y"), onSelect: () => exec("redo") },
      "-",
      { label: "Cut", shortcut: keys("Ctrl+X"), disabled: !hasSel || secret, onSelect: () => exec("cut") },
      { label: "Copy", shortcut: keys("Ctrl+C"), disabled: !hasSel || secret, onSelect: () => exec("copy") },
      { label: "Paste", shortcut: keys("Ctrl+V"), onSelect: paste },
      "-",
      { label: "Select all", shortcut: keys("Ctrl+A"), onSelect: () => { field.focus(); field.select?.() || exec("selectAll"); } },
    ];
  }
  if (selected) {
    return [
      { label: "Copy", shortcut: keys("Ctrl+C"), icon: "copy", onSelect: () => navigator.clipboard.writeText(selected) },
      askNova && { label: "Ask Nova about this", icon: "chat", onSelect: () => askNova(selected) },
    ];
  }
  return null;
}

/* ---- provider ---------------------------------------------------------- */

let nextId = 1;

export function UiProvider({ children, askNova, layerClass = "", layerStyle }) {
  const [menu, setMenu] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [ask, setAsk] = useState(null);
  const returnFocus = useRef(null);
  const timers = useRef(new Map());
  const pending = useRef(new Map()); // undoable commits not yet sent
  const askNovaRef = useRef(askNova);
  askNovaRef.current = askNova;

  // Press and hold opens the right-click menu on touch screens. Android fires
  // contextmenu itself on a long press (then this timer is cancelled); iOS
  // never does, so this is the only way there.
  useEffect(() => {
    let timer = null;
    let start = null;
    let fired = false;
    const cancel = () => { clearTimeout(timer); timer = null; };
    const down = (e) => {
      if (e.touches.length !== 1) return cancel();
      const t = e.touches[0];
      start = { x: t.clientX, y: t.clientY, target: e.target };
      fired = false;
      cancel();
      timer = setTimeout(() => {
        timer = null;
        fired = true;
        start.target.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: start.x, clientY: start.y, button: 2 }));
      }, 500);
    };
    const move = (e) => {
      const t = e.touches[0];
      if (start && t && Math.hypot(t.clientX - start.x, t.clientY - start.y) > 10) cancel();
    };
    const up = (e) => { cancel(); if (fired) { e.preventDefault(); fired = false; } };
    const native = () => cancel();
    document.addEventListener("touchstart", down, { passive: true });
    document.addEventListener("touchmove", move, { passive: true });
    document.addEventListener("touchend", up);
    document.addEventListener("touchcancel", cancel);
    document.addEventListener("contextmenu", native, true);
    return () => {
      cancel();
      document.removeEventListener("touchstart", down);
      document.removeEventListener("touchmove", move);
      document.removeEventListener("touchend", up);
      document.removeEventListener("touchcancel", cancel);
      document.removeEventListener("contextmenu", native, true);
    };
  }, []);

  const closeMenu = useCallback((restore) => {
    setMenu(null);
    if (restore) returnFocus.current?.focus?.();
  }, []);

  const openMenu = useCallback((event, items, opts = {}) => {
    event.preventDefault();
    event.stopPropagation();
    returnFocus.current = document.activeElement;
    let x = event.clientX;
    let y = event.clientY;
    if (!x && !y) { // opened from the keyboard (Menu key, Shift+F10)
      const r = event.currentTarget?.getBoundingClientRect?.() || event.target.getBoundingClientRect();
      x = r.left + 12; y = r.bottom - 4;
    }
    setMenu({ x, y, items, ...opts });
  }, []);

  const dismiss = useCallback((id, early) => {
    setToasts((all) => all.filter((t) => t.id !== id));
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    const commit = pending.current.get(id);
    if (commit && early) { pending.current.delete(id); commit(); }
  }, []);

  const toast = useCallback((message, opts = {}) => {
    const id = nextId++;
    setToasts((all) => [...all.slice(-3), { id, message, ...opts }]);
    timers.current.set(id, setTimeout(() => dismiss(id, true), opts.timeout || 5000));
    return id;
  }, [dismiss]);

  /** Remove something now and really delete it a few seconds later, unless
   * the user presses Undo. apply() hides it, revert() brings it back, and
   * commit() is the real delete; a failed commit reverts and says so. */
  const undoable = useCallback(({ message, apply, revert, commit }) => {
    apply();
    let settled = false;
    const run = async () => {
      if (settled) return;
      settled = true;
      try { await commit(); } catch (e) { revert(); toast(`Couldn't finish: ${e.message}`, { error: true }); }
    };
    const id = toast(message, {
      timeout: 6000,
      action: { label: "Undo", run: () => { settled = true; pending.current.delete(id); revert(); } },
    });
    pending.current.set(id, run);
  }, [toast]);

  const confirm = useCallback((opts) => new Promise((resolve) => {
    returnFocus.current = document.activeElement;
    setAsk({ ...opts, resolve });
  }), []);

  // Leaving Nova (reload, quit) sends deletes that were waiting on Undo.
  useEffect(() => {
    const flush = () => { pending.current.forEach((run) => run()); pending.current.clear(); };
    window.addEventListener("beforeunload", flush);
    return () => window.removeEventListener("beforeunload", flush);
  }, []);

  // Anywhere without its own menu: text fields get Cut/Copy/Paste, selected
  // text gets Copy. Electron shows no menu at all by default.
  useEffect(() => {
    const onContext = (e) => {
      if (e.defaultPrevented) return;
      const items = editMenu(e.target, askNovaRef.current);
      if (items) openMenu(e, items);
      else e.preventDefault();
    };
    document.addEventListener("contextmenu", onContext);
    return () => document.removeEventListener("contextmenu", onContext);
  }, [openMenu]);

  const value = useMemo(() => ({ openMenu, closeMenu, toast, undoable, confirm }), [openMenu, closeMenu, toast, undoable, confirm]);
  return (
    <UiContext.Provider value={value}>
      {children}
      <div className={`p-layer ${layerClass}`} style={layerStyle}>
        {menu && <Menu menu={menu} onClose={closeMenu} />}
        <Toasts toasts={toasts} dismiss={dismiss} />
        {ask && <Confirm ask={ask} onAnswer={(yes) => { ask.resolve(yes); setAsk(null); returnFocus.current?.focus?.(); }} />}
      </div>
    </UiContext.Provider>
  );
}

/* ---- selection --------------------------------------------------------- */

/** Multi-select over an ordered list of ids, the way file managers do it:
 * click a checkbox to toggle, Shift+click for a range, Ctrl+click to add or
 * remove, and once anything is selected a plain click toggles too. */
export function useSelection(ids) {
  const [selected, setSelected] = useState(() => new Set());
  const anchor = useRef(null);
  const key = ids.join("\u0001");

  // Forget ids that are no longer in the list (deleted, filtered out).
  useEffect(() => {
    setSelected((s) => {
      const valid = new Set(ids);
      const next = new Set([...s].filter((id) => valid.has(id)));
      return next.size === s.size ? s : next;
    });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = useCallback((next) => setSelected(new Set(next)), []);
  const clear = useCallback(() => { setSelected(new Set()); anchor.current = null; }, []);
  const all = useCallback(() => setSelected(new Set(ids)), [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = useCallback((id, event) => {
    setSelected((s) => {
      const next = new Set(s);
      if (event?.shiftKey && anchor.current != null && ids.includes(anchor.current)) {
        const [a, b] = [ids.indexOf(anchor.current), ids.indexOf(id)].sort((x, y) => x - y);
        ids.slice(a, b + 1).forEach((x) => next.add(x));
        return next;
      }
      if (next.has(id)) next.delete(id); else next.add(id);
      anchor.current = id;
      return next;
    });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Row click: only selects when a modifier is held or selection mode is on.
   * Returns true when the click was used for selecting. */
  const rowClick = useCallback((id, event) => {
    if (event.shiftKey || event.ctrlKey || event.metaKey || selected.size > 0) {
      if (event.target.closest("button, a, input, textarea, select")) return false;
      event.preventDefault();
      toggle(id, event);
      return true;
    }
    return false;
  }, [selected, toggle]);

  /** Right-click on a row: an unselected row becomes the selection (like
   * Explorer); a selected one keeps the whole selection. Returns the ids the
   * menu should act on. */
  const forMenu = useCallback((id) => {
    if (selected.has(id)) return [...selected];
    setSelected(new Set([id]));
    anchor.current = id;
    return [id];
  }, [selected]);

  return { selected, count: selected.size, has: (id) => selected.has(id), toggle, rowClick, forMenu, set, clear, all,
    allSelected: ids.length > 0 && selected.size === ids.length };
}

/** Esc clears, Ctrl+A selects all and Delete acts, while focus is inside the
 * list and not in a text field. */
export function useListKeys(ref, sel, { onDelete } = {}) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const onKey = (e) => {
      if (editable(e.target)) return;
      if (e.key === "Escape" && sel.count) { e.preventDefault(); sel.clear(); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); sel.all(); }
      else if ((e.key === "Delete" || e.key === "Backspace") && sel.count && onDelete) { e.preventDefault(); onDelete([...sel.selected]); }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [ref, sel, onDelete]);
}

export function Checkbox({ checked, mixed, onChange, label }) {
  return (
    <button type="button" role="checkbox" className="p-check" aria-checked={mixed ? "mixed" : Boolean(checked)} aria-label={label}
      title={label} onClick={(e) => { e.stopPropagation(); onChange(e); }}>
      <svg viewBox="0 0 16 16" aria-hidden="true">{mixed ? <path d="M4 8h8" /> : checked ? <path d="M3.5 8.5l3 3 6-7" /> : null}</svg>
    </button>
  );
}

/** A bar that appears while things are selected: count, Select all/none, and
 * the actions that apply to the selection. */
export function SelectionBar({ sel, total, noun = "item", nouns, children }) {
  const n = sel.count;
  return (
    <div className={`p-selbar${n ? " on" : ""}`} role="toolbar" aria-label="Selection">
      <Checkbox checked={sel.allSelected} mixed={n > 0 && !sel.allSelected}
        label={sel.allSelected ? "Select none" : "Select all"} onChange={() => (sel.allSelected ? sel.clear() : sel.all())} />
      <span className="n">{n ? `${n} of ${total} selected` : `Select all ${total} ${total === 1 ? noun : nouns || `${noun}s`}`}</span>
      <span className="sp" />
      {n > 0 && <button className="p-link" onClick={sel.clear}>Clear</button>}
      {children}
    </div>
  );
}

/** Draw a popup in the shared overlay layer, above every page -- a fixed
 * element inside a page is otherwise positioned (and stacked) within it. */
export function Overlay({ children }) {
  const layer = typeof document !== "undefined" ? document.querySelector(".p-layer") : null;
  return layer ? createPortal(children, layer) : children;
}
