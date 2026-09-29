"""Windows UI Automation: Nova's way of pressing things without the mouse.

Every modern Windows app publishes an accessibility tree -- the same one a
screen reader walks. Through it a button can be *invoked*, a checkbox
*toggled*, a list item *selected* and a text box *given a value*, directly,
with no pointer involved. That is what makes Nova's own cursor possible:
the drawn pointer shows where Nova is acting, and the action itself goes
through here, so the user's real mouse is never touched.

It also works on a window that is covered -- by a fullscreen game, say --
because the tree does not care what is painted on top. `controls()` reads a
window's controls by name without a screenshot, and `act()` presses one.

All COM work happens on one dedicated thread. UI Automation objects belong to
the apartment that created them, and handing them between asyncio's worker
threads is how you get RPC_E_WRONG_THREAD at the worst moment.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sys

logger = logging.getLogger(__name__)

AVAILABLE = sys.platform == "win32"
_import_error: str | None = None
if AVAILABLE:
    try:
        import comtypes
        import comtypes.client
    except Exception as exc:  # noqa: BLE001 -- reported at the point of use
        AVAILABLE = False
        _import_error = f"UI Automation unavailable: {exc}"
else:
    _import_error = "UI Automation is Windows-only."


class UiaError(Exception):
    """Plain-language failure, safe to hand to the model."""


# Control type ids (UIAutomationClient.h) -> the words a person would use.
CONTROL_TYPES = {
    50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combobox",
    50004: "edit", 50005: "hyperlink", 50006: "image", 50007: "listitem",
    50008: "list", 50009: "menu", 50010: "menubar", 50011: "menuitem",
    50012: "progressbar", 50013: "radio", 50014: "scrollbar", 50015: "slider",
    50016: "spinner", 50017: "statusbar", 50018: "tab", 50019: "tabitem",
    50020: "text", 50021: "toolbar", 50022: "tooltip", 50023: "tree",
    50024: "treeitem", 50025: "custom", 50026: "group", 50027: "thumb",
    50028: "datagrid", 50029: "dataitem", 50030: "document", 50031: "splitbutton",
    50032: "window", 50033: "pane", 50034: "header", 50035: "headeritem",
    50036: "table", 50037: "titlebar", 50038: "separator",
}

# Pattern ids, and the verb each one means.
INVOKE, SELECTION_ITEM, VALUE, EXPAND_COLLAPSE, TOGGLE, LEGACY = 10000, 10010, 10002, 10005, 10015, 10018

# Types worth listing to a model: things you can act on, plus text you can read.
ACTIONABLE = {"button", "checkbox", "combobox", "edit", "hyperlink", "listitem", "menuitem",
              "radio", "slider", "spinner", "tabitem", "treeitem", "splitbutton", "dataitem",
              "document", "headeritem"}
READABLE = {"text", "statusbar", "titlebar"}

_executor: concurrent.futures.ThreadPoolExecutor | None = None
_automation = None
_module = None
# Per window: the elements handed out by the last controls() call, by ref.
_refs: dict[int, list] = {}


def _init_thread() -> None:
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)


def _run(fn, *args):
    """Run `fn` on the UIA thread."""
    global _executor
    if not AVAILABLE:
        raise UiaError(_import_error or "UI Automation unavailable.")
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="nova-uia", initializer=_init_thread)
    return asyncio.wrap_future(_executor.submit(fn, *args))


def _uia():
    global _automation, _module
    if _automation is None:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as module
        _module = module
        _automation = comtypes.client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
    return _automation, _module


# ---------------------------------------------------------------- pure helpers

def normalize(text: str) -> str:
    return " ".join((text or "").split()).lower()


def match_by_name(entries: list[dict], wanted: str) -> dict | None:
    """The control whose name best matches `wanted`: exact first, then the
    shortest name containing it, actionable controls before plain text --
    "Save" should find the Save button, not a label that says "Save As..."."""
    target = normalize(wanted)
    if not target:
        return None
    exact = [e for e in entries if normalize(e["name"]) == target]
    partial = [e for e in entries if target in normalize(e["name"])]
    for pool in (exact, partial):
        if not pool:
            continue
        pool = sorted(pool, key=lambda e: (e["type"] not in ACTIONABLE, e.get("offscreen", False), len(e["name"])))
        return pool[0]
    return None


def describe(entries: list[dict], limit: int = 200) -> str:
    """Lines a model can act on: `[ref] type "name" (what it can do)`."""
    lines = []
    for e in entries[:limit]:
        verbs = ", ".join(e.get("can", []))
        line = f"[{e['ref']}] {e['type']} \"{e['name']}\""
        if e.get("value") is not None:
            line += f" = \"{e['value']}\""
        if e.get("toggled") is not None:
            line += " [on]" if e["toggled"] else " [off]"
        if verbs:
            line += f" ({verbs})"
        if not e.get("enabled", True):
            line += " (disabled)"
        if e.get("offscreen"):
            line += " (off screen)"
        lines.append(line)
    if len(entries) > limit:
        lines.append(f"... {len(entries) - limit} more not shown")
    return "\n".join(lines)


# ---------------------------------------------------------------- COM side

def _pattern(element, pattern_id: int):
    auto, mod = _uia()
    interfaces = {
        INVOKE: mod.IUIAutomationInvokePattern,
        SELECTION_ITEM: mod.IUIAutomationSelectionItemPattern,
        VALUE: mod.IUIAutomationValuePattern,
        EXPAND_COLLAPSE: mod.IUIAutomationExpandCollapsePattern,
        TOGGLE: mod.IUIAutomationTogglePattern,
        LEGACY: mod.IUIAutomationLegacyIAccessiblePattern,
    }
    try:
        raw = element.GetCurrentPattern(pattern_id)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return raw.QueryInterface(interfaces[pattern_id])
    except Exception:  # noqa: BLE001
        return None


def _entry(element, ref: int) -> dict | None:
    try:
        type_name = CONTROL_TYPES.get(element.CurrentControlType, "element")
        name = (element.CurrentName or "").strip()
        rect = element.CurrentBoundingRectangle
        entry = {
            "ref": ref,
            "type": type_name,
            "name": name[:120],
            "enabled": bool(element.CurrentIsEnabled),
            "offscreen": bool(element.CurrentIsOffscreen),
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "can": [],
        }
    except Exception:  # noqa: BLE001 -- the element went away mid-walk
        return None
    if _pattern(element, INVOKE):
        entry["can"].append("press")
    toggle = _pattern(element, TOGGLE)
    if toggle:
        entry["can"].append("toggle")
        try:
            entry["toggled"] = toggle.CurrentToggleState == 1
        except Exception:  # noqa: BLE001
            pass
    if _pattern(element, SELECTION_ITEM):
        entry["can"].append("select")
    if _pattern(element, EXPAND_COLLAPSE):
        entry["can"].append("expand")
    value = _pattern(element, VALUE)
    if value:
        try:
            if not value.CurrentIsReadOnly:
                entry["can"].append("type")
            # A password box reports IsPassword; its value is never read.
            if not element.CurrentIsPassword:
                entry["value"] = (value.CurrentValue or "")[:200]
            else:
                entry["secret"] = True
        except Exception:  # noqa: BLE001
            pass
    return entry


def _element_for_window(hwnd: int):
    auto, _ = _uia()
    try:
        return auto.ElementFromHandle(hwnd)
    except Exception as exc:  # noqa: BLE001
        raise UiaError(f"That window is gone or does not expose its controls ({exc}).") from exc


def _controls_sync(hwnd: int, limit: int) -> list[dict]:
    auto, _ = _uia()
    root = _element_for_window(hwnd)
    condition = auto.ControlViewCondition
    found = root.FindAll(4, condition)  # TreeScope_Descendants
    elements, entries = [], []
    for i in range(found.Length):
        if len(entries) >= limit:
            break
        element = found.GetElement(i)
        entry = _entry(element, len(elements))
        if entry is None:
            continue
        if entry["type"] not in ACTIONABLE and entry["type"] not in READABLE:
            continue
        if not entry["name"] and not entry["can"]:
            continue
        elements.append(element)
        entries.append(entry)
    _refs[hwnd] = elements
    return entries


async def controls(hwnd: int, limit: int = 250) -> list[dict]:
    """The window's controls a person could act on or read, numbered. Works
    on a covered or minimised window: it reads the tree, not the pixels."""
    return await _run(_controls_sync, hwnd, limit)


def _act_on(element, entry: dict, action: str, text: str | None) -> str:
    """Do `action` to one element through its patterns. Returns the method."""
    if action == "type":
        value = _pattern(element, VALUE)
        if not value:
            raise UiaError(f"{entry['type']} \"{entry['name']}\" does not take typed text.")
        value.SetValue(text or "")
        return "set its value"
    order = {
        "press": (INVOKE, TOGGLE, SELECTION_ITEM, EXPAND_COLLAPSE, LEGACY),
        "toggle": (TOGGLE, INVOKE, LEGACY),
        "select": (SELECTION_ITEM, INVOKE, LEGACY),
        "expand": (EXPAND_COLLAPSE, INVOKE),
    }.get(action)
    if order is None:
        raise UiaError(f"Unknown action {action!r}; use press, toggle, select, expand or type.")
    for pattern_id in order:
        pattern = _pattern(element, pattern_id)
        if not pattern:
            continue
        if pattern_id == INVOKE:
            pattern.Invoke()
            return "pressed it"
        if pattern_id == TOGGLE:
            pattern.Toggle()
            return "toggled it"
        if pattern_id == SELECTION_ITEM:
            pattern.Select()
            return "selected it"
        if pattern_id == EXPAND_COLLAPSE:
            state = pattern.CurrentExpandCollapseState
            (pattern.Collapse if state == 1 else pattern.Expand)()
            return "expanded it" if state != 1 else "collapsed it"
        if pattern_id == LEGACY:
            pattern.DoDefaultAction()
            return "used its default action"
    raise UiaError(f"{entry['type']} \"{entry['name']}\" cannot be {action}ed through its accessibility interface.")


REPLACE_REFUSAL = (
    "{control} already holds {chars} characters. Typing replaces all of it -- and a document "
    "restored by its app (Notepad reopens your last files) can be real work, not a blank page. "
    "Nothing was changed. If replacing it is really what is wanted, call again with replace=true."
)


def _act_sync(hwnd: int, ref: int | None, name: str | None, action: str, text: str | None,
              replace: bool = False) -> dict:
    if ref is None and not name:
        raise UiaError("Say which control: a ref from app_controls, or its name.")
    elements = _refs.get(hwnd)
    if elements is None or name:
        # Names are re-resolved against a fresh read, so they survive the UI
        # changing between calls; refs belong to the last read on purpose.
        entries = _controls_sync(hwnd, 400)
        elements = _refs[hwnd]
    else:
        entries = None
    if name:
        chosen = match_by_name(entries or [], name)
        if chosen is None:
            raise UiaError(f"No control named like {name!r} in that window. Call app_controls to see what is there.")
        ref = chosen["ref"]
    if ref is None or not (0 <= ref < len(elements)):
        raise UiaError(f"No control {ref} -- refs come from the last app_controls call.")
    element = elements[ref]
    entry = _entry(element, ref)
    if entry is None:
        raise UiaError(f"Control {ref} is gone -- the window changed. Call app_controls again.")
    if not entry["enabled"]:
        raise UiaError(f"{entry['type']} \"{entry['name']}\" is disabled.")
    if action == "type" and not replace:
        existing = _current_text(element)
        if existing:
            raise UiaError(REPLACE_REFUSAL.format(
                control=f"{entry['type']} \"{entry['name']}\"", chars=len(existing)))
    method = _act_on(element, entry, action, text)
    return {"control": f"{entry['type']} \"{entry['name']}\"", "how": method, "rect": entry["rect"]}


async def act(hwnd: int, *, ref: int | None = None, name: str | None = None,
              action: str = "press", text: str | None = None, replace: bool = False) -> dict:
    return await _run(_act_sync, hwnd, ref, name, action, text, replace)


def _current_text(element) -> str:
    """What a field holds now -- read only to decide whether typing would
    destroy something, and never returned. A password box counts as holding
    text without being read."""
    try:
        if element.CurrentIsPassword:
            return "*"
    except Exception:  # noqa: BLE001
        pass
    value = _pattern(element, VALUE)
    if not value:
        return ""
    try:
        return (value.CurrentValue or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _act_at_sync(x: int, y: int) -> dict | None:
    """Press whatever is at a screen point through UIA, walking up from the
    deepest element (often a text label inside the button) to the nearest one
    that can be pressed. None when nothing there can be."""
    auto, mod = _uia()
    point = mod.tagPOINT(x, y)
    try:
        element = auto.ElementFromPoint(point)
    except Exception:  # noqa: BLE001
        return None
    walker = auto.ControlViewWalker
    for _ in range(4):
        if element is None:
            return None
        entry = _entry(element, 0)
        if entry and entry["enabled"] and any(v in entry["can"] for v in ("press", "toggle", "select", "expand")):
            try:
                how = _act_on(element, entry, "press", None)
            except Exception:  # noqa: BLE001 -- fall through to the next rung of the ladder
                return None
            return {"control": f"{entry['type']} \"{entry['name']}\"", "how": how}
        try:
            element = walker.GetParentElement(element)
        except Exception:  # noqa: BLE001
            return None
    return None


async def act_at(x: int, y: int) -> dict | None:
    return await _run(_act_at_sync, x, y)


def act_at_blocking(x: int, y: int, timeout: float = 10.0) -> dict | None:
    """act_at for code already on a worker thread (desktop.click's ladder)."""
    global _executor
    if not AVAILABLE:
        return None
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="nova-uia", initializer=_init_thread)
    return _executor.submit(_act_at_sync, x, y).result(timeout)
