"""macOS accessibility: an app's buttons, fields and menus, the way uia.py
reads them on Windows. Same entries, same verbs (press, toggle, select,
expand, type), so app_controls / app_click / app_type work the same.

Needs the Accessibility permission (System Settings > Privacy & Security >
Accessibility), which onboarding asks for.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ROLES = {
    "AXButton": "button", "AXCheckBox": "checkbox", "AXRadioButton": "radio", "AXTextField": "edit",
    "AXTextArea": "edit", "AXSecureTextField": "edit", "AXComboBox": "combobox", "AXPopUpButton": "combobox",
    "AXLink": "hyperlink", "AXMenuItem": "menuitem", "AXMenuBarItem": "menuitem", "AXMenuButton": "button",
    "AXRow": "listitem", "AXCell": "dataitem", "AXSlider": "slider", "AXIncrementor": "spinner",
    "AXStaticText": "text", "AXDisclosureTriangle": "treeitem", "AXTab": "tabitem", "AXWebArea": "document",
    "AXHeading": "text", "AXSwitch": "checkbox", "AXToggle": "checkbox", "AXColorWell": "button",
    "AXOutlineRow": "treeitem",
}
MAX_DEPTH = 30


class AxError(Exception):
    pass


def _ax():
    try:
        import ApplicationServices as AS
        return AS
    except Exception as exc:  # noqa: BLE001
        raise AxError(f"macOS accessibility needs pyobjc-framework-ApplicationServices ({exc}).") from exc


def _trusted() -> None:
    AS = _ax()
    if not AS.AXIsProcessTrusted():
        raise AxError("Nova needs the Accessibility permission to use other apps' controls: System Settings > "
                      "Privacy & Security > Accessibility, then switch Nova on.")


def _get(element, attribute: str):
    AS = _ax()
    try:
        err, value = AS.AXUIElementCopyAttributeValue(element, attribute, None)
    except Exception:  # noqa: BLE001
        return None
    return value if err == 0 else None


def _actions(element) -> list[str]:
    AS = _ax()
    try:
        err, names = AS.AXUIElementCopyActionNames(element, None)
        return list(names or []) if err == 0 else []
    except Exception:  # noqa: BLE001
        return []


def _settable(element, attribute: str) -> bool:
    AS = _ax()
    try:
        err, ok = AS.AXUIElementIsAttributeSettable(element, attribute, None)
        return err == 0 and bool(ok)
    except Exception:  # noqa: BLE001
        return False


def _rect(element) -> list[int]:
    AS = _ax()
    pos, size = _get(element, "AXPosition"), _get(element, "AXSize")
    try:
        _ok, p = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
        _ok2, s = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
        return [int(p.x), int(p.y), int(p.x + s.width), int(p.y + s.height)]
    except Exception:  # noqa: BLE001
        return [0, 0, 0, 0]


def _entry(element, ref: int) -> dict | None:
    role = _get(element, "AXRole")
    if role is None:
        return None
    kind = ROLES.get(str(role), "element")
    name = _get(element, "AXTitle") or _get(element, "AXDescription") or _get(element, "AXLabel") or ""
    if not name and kind == "text":
        name = _get(element, "AXValue") or ""
    actions = _actions(element)
    entry = {"ref": ref, "type": kind, "name": str(name).strip()[:120],
             "enabled": _get(element, "AXEnabled") is not False, "offscreen": False,
             "rect": _rect(element), "can": []}
    if "AXPress" in actions:
        entry["can"].append("toggle" if kind in ("checkbox", "radio") else "press")
    if kind in ("listitem", "dataitem", "tabitem", "treeitem") or _settable(element, "AXSelected"):
        entry["can"].append("select")
    if "AXShowMenu" in actions or _settable(element, "AXExpanded") or kind == "treeitem":
        entry["can"].append("expand")
    if kind == "edit" or (kind in ("combobox", "slider", "spinner") and _settable(element, "AXValue")):
        if _settable(element, "AXValue"):
            entry["can"].append("type")
    if kind in ("checkbox", "radio"):
        value = _get(element, "AXValue")
        if value is not None:
            entry["toggled"] = bool(value)
    if str(role) == "AXSecureTextField":
        entry["secret"] = True
    elif kind in ("edit", "combobox", "slider", "spinner"):
        value = _get(element, "AXValue")
        if value is not None:
            entry["value"] = str(value)[:200]
    return entry


def _app_windows(pid: int) -> list:
    AS = _ax()
    return list(_get(AS.AXUIElementCreateApplication(int(pid)), "AXWindows") or [])


def _window_element(pid: int, rect) -> object | None:
    """The accessibility element of the window at these bounds."""
    windows = _app_windows(pid)
    if not windows:
        return None
    best, best_d = None, None
    for w in windows:
        r = _rect(w)
        d = sum(abs(a - b) for a, b in zip(r, rect))
        if best_d is None or d < best_d:
            best, best_d = w, d
    return best


def window_title(pid: int, rect) -> str:
    w = _window_element(pid, rect)
    return str(_get(w, "AXTitle") or "") if w is not None else ""


def raise_window(pid: int, rect) -> None:
    w = _window_element(pid, rect)
    if w is not None:
        _ax().AXUIElementPerformAction(w, "AXRaise")


def close_window(pid: int, rect) -> bool:
    w = _window_element(pid, rect)
    button = _get(w, "AXCloseButton") if w is not None else None
    if button is None:
        return False
    return _ax().AXUIElementPerformAction(button, "AXPress") == 0


# Per window id: the elements handed out by the last controls() call, by ref.
_refs: dict[int, list] = {}


def controls_sync(wid: int, limit: int = 250) -> list[dict]:
    from . import desktop_os
    _trusted()
    w = desktop_os.window(wid)
    if not w or not w.get("pid"):
        raise AxError("That window is gone.")
    root = _window_element(w["pid"], w["rect"])
    if root is None:
        raise AxError("That window doesn't expose its controls to accessibility.")
    from . import uia
    elements, entries, queue = [], [], [(root, 0)]
    while queue and len(entries) < limit:
        element, depth = queue.pop(0)
        entry = _entry(element, len(elements))
        if entry and (entry["type"] in uia.ACTIONABLE or entry["type"] in uia.READABLE) and (entry["name"] or entry["can"]):
            elements.append(element)
            entries.append(entry)
        if depth < MAX_DEPTH:
            queue.extend((c, depth + 1) for c in (_get(element, "AXChildren") or []))
    _refs[int(wid)] = elements
    return entries


def _current_text(element) -> str:
    if str(_get(element, "AXRole")) == "AXSecureTextField":
        return "*"
    value = _get(element, "AXValue")
    return str(value).strip() if isinstance(value, str) else ""


def act_on(element, entry: dict, action: str, text: str | None) -> str:
    AS = _ax()
    if action == "type":
        if AS.AXUIElementSetAttributeValue(element, "AXValue", text or "") != 0:
            raise AxError(f"{entry['type']} \"{entry['name']}\" does not take typed text.")
        return "set its value"
    actions = _actions(element)
    if action in ("press", "toggle") and "AXPress" in actions:
        AS.AXUIElementPerformAction(element, "AXPress")
        return "toggled it" if action == "toggle" else "pressed it"
    if action == "select":
        if _settable(element, "AXSelected"):
            AS.AXUIElementSetAttributeValue(element, "AXSelected", True)
            return "selected it"
        if "AXPress" in actions:
            AS.AXUIElementPerformAction(element, "AXPress")
            return "selected it"
    if action == "expand":
        if _settable(element, "AXExpanded"):
            now = bool(_get(element, "AXExpanded"))
            AS.AXUIElementSetAttributeValue(element, "AXExpanded", not now)
            return "collapsed it" if now else "expanded it"
        if "AXShowMenu" in actions:
            AS.AXUIElementPerformAction(element, "AXShowMenu")
            return "opened its menu"
    if action == "press" and "AXShowMenu" in actions:
        AS.AXUIElementPerformAction(element, "AXShowMenu")
        return "opened its menu"
    if action not in ("press", "toggle", "select", "expand"):
        raise AxError(f"Unknown action {action!r}; use press, toggle, select, expand or type.")
    raise AxError(f"{entry['type']} \"{entry['name']}\" cannot be {action}ed through accessibility.")


def act_sync(wid: int, ref: int | None, name: str | None, action: str, text: str | None, replace: bool = False) -> dict:
    from . import uia
    if ref is None and not name:
        raise AxError("Say which control: a ref from app_controls, or its name.")
    elements = _refs.get(int(wid))
    entries = None
    if elements is None or name:
        entries = controls_sync(wid, 400)
        elements = _refs[int(wid)]
    if name:
        chosen = uia.match_by_name(entries or [], name)
        if chosen is None:
            raise AxError(f"No control named like {name!r} in that window. Call app_controls to see what is there.")
        ref = chosen["ref"]
    if ref is None or not (0 <= ref < len(elements)):
        raise AxError(f"No control {ref} -- refs come from the last app_controls call.")
    element = elements[ref]
    entry = _entry(element, ref)
    if entry is None:
        raise AxError(f"Control {ref} is gone -- the window changed. Call app_controls again.")
    if not entry["enabled"]:
        raise AxError(f"{entry['type']} \"{entry['name']}\" is disabled.")
    if action == "type" and not replace:
        existing = _current_text(element)
        if existing:
            raise AxError(uia.REPLACE_REFUSAL.format(control=f"{entry['type']} \"{entry['name']}\"", chars=len(existing)))
    how = act_on(element, entry, action, text)
    return {"control": f"{entry['type']} \"{entry['name']}\"", "how": how, "rect": entry["rect"]}


def act_at_sync(x: int, y: int) -> dict | None:
    """Press whatever is at a screen point, walking up from the deepest
    element to the nearest one that can be pressed."""
    AS = _ax()
    if not AS.AXIsProcessTrusted():
        return None
    try:
        err, element = AS.AXUIElementCopyElementAtPosition(AS.AXUIElementCreateSystemWide(), float(x), float(y), None)
    except Exception:  # noqa: BLE001
        return None
    if err != 0:
        return None
    for _ in range(4):
        if element is None:
            return None
        entry = _entry(element, 0)
        if entry and entry["enabled"] and any(v in entry["can"] for v in ("press", "toggle", "select", "expand")):
            try:
                how = act_on(element, entry, "press", None)
            except Exception:  # noqa: BLE001
                return None
            return {"control": f"{entry['type']} \"{entry['name']}\"", "how": how}
        element = _get(element, "AXParent")
    return None
