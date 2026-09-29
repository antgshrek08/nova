"""Linux accessibility: an app's buttons, fields and menus through AT-SPI,
the system screen readers use on GNOME, KDE and the rest. Same entries and
verbs as uia.py on Windows and ax_mac.py on macOS.

Spoken to directly over D-Bus (jeepney, pure Python), so there is nothing to
compile and no system Python bindings to match. AT-SPI works the same under
X11 and Wayland.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

ACC = "org.a11y.atspi.Accessible"
ROLES = {
    "push button": "button", "button": "button", "toggle button": "checkbox", "check box": "checkbox",
    "radio button": "radio", "entry": "edit", "password text": "edit", "text": "edit", "spin button": "spinner",
    "combo box": "combobox", "link": "hyperlink", "menu item": "menuitem", "check menu item": "menuitem",
    "radio menu item": "menuitem", "list item": "listitem", "table cell": "dataitem", "tree item": "treeitem",
    "page tab": "tabitem", "slider": "slider", "label": "text", "static": "text", "heading": "text",
    "status bar": "statusbar", "document web": "document", "document frame": "document",
    "document text": "document", "paragraph": "text", "menu": "menuitem",
}
# AT-SPI StateType bits.
CHECKED, EDITABLE, EXPANDABLE, EXPANDED, ENABLED, SELECTABLE, SENSITIVE, SHOWING = 4, 7, 9, 10, 8, 22, 24, 25
PRESS_WORDS = ("click", "press", "activate", "jump", "open")
MAX_NODES = 4000


class AxError(Exception):
    pass


_local = threading.local()


def _conn():
    c = getattr(_local, "conn", None)
    if c is None:
        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.io.blocking import open_dbus_connection
        except Exception as exc:  # noqa: BLE001
            raise AxError(f"Linux accessibility needs jeepney ({exc}). Run install.sh again.") from exc
        try:
            with open_dbus_connection(bus="SESSION") as session:
                reply = session.send_and_get_reply(new_method_call(
                    DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.a11y.Bus"), "GetAddress"))
            c = open_dbus_connection(bus=reply.body[0])
        except Exception as exc:  # noqa: BLE001
            raise AxError("The accessibility bus isn't running. Turn on assistive technologies "
                          "(GNOME: gsettings set org.gnome.desktop.interface toolkit-accessibility true) "
                          f"and sign in again. ({exc})") from exc
        _local.conn = c
    return c


def _call(ref, interface: str, method: str, signature: str = "", body: tuple = ()):
    from jeepney import DBusAddress, new_method_call
    name, path = ref
    reply = _conn().send_and_get_reply(new_method_call(DBusAddress(path, bus_name=name, interface=interface),
                                                       method, signature, body), timeout=3)
    if reply.header.message_type.name == "error":
        raise AxError(str(reply.body[0]) if reply.body else "accessibility call failed")
    return reply.body


def _prop(ref, interface: str, prop: str):
    try:
        return _call(ref, "org.freedesktop.DBus.Properties", "Get", "ss", (interface, prop))[0][1]
    except Exception:  # noqa: BLE001
        return None


def _children(ref) -> list:
    try:
        return [tuple(c) for c in _call(ref, ACC, "GetChildren")[0]]
    except Exception:  # noqa: BLE001
        return []


def _states(ref) -> int:
    try:
        words = _call(ref, ACC, "GetState")[0]
        return sum(int(w) << (32 * i) for i, w in enumerate(words))
    except Exception:  # noqa: BLE001
        return 0


def _has(states: int, bit: int) -> bool:
    return bool(states >> bit & 1)


def _interfaces(ref) -> list[str]:
    try:
        return list(_call(ref, ACC, "GetInterfaces")[0])
    except Exception:  # noqa: BLE001
        return []


def _actions(ref) -> list[str]:
    n = _prop(ref, "org.a11y.atspi.Action", "NActions") or 0
    names = []
    for i in range(int(n)):
        try:
            names.append(str(_call(ref, "org.a11y.atspi.Action", "GetName", "i", (i,))[0]).lower())
        except Exception:  # noqa: BLE001
            names.append("")
    return names


def _rect(ref) -> list[int]:
    try:
        x, y, w, h = _call(ref, "org.a11y.atspi.Component", "GetExtents", "u", (0,))[0]
        return [int(x), int(y), int(x + w), int(y + h)]
    except Exception:  # noqa: BLE001
        return [0, 0, 0, 0]


def _text(ref) -> str:
    try:
        return str(_call(ref, "org.a11y.atspi.Text", "GetText", "ii", (0, -1))[0])
    except Exception:  # noqa: BLE001
        return ""


def _entry(ref, index: int) -> dict | None:
    try:
        role = str(_call(ref, ACC, "GetRoleName")[0])
    except Exception:  # noqa: BLE001
        return None
    states = _states(ref)
    ifaces = _interfaces(ref)
    kind = ROLES.get(role, "element")
    if kind == "edit" and not _has(states, EDITABLE):
        kind = "text"
    name = str(_prop(ref, ACC, "Name") or "").strip()
    if not name and kind == "text":
        name = _text(ref).strip()
    actions = _actions(ref) if "org.a11y.atspi.Action" in ifaces else []
    entry = {"ref": index, "type": kind, "name": name[:120],
             "enabled": _has(states, ENABLED) or _has(states, SENSITIVE),
             "offscreen": not _has(states, SHOWING), "rect": _rect(ref), "can": []}
    if kind in ("checkbox", "radio"):
        entry["toggled"] = _has(states, CHECKED)
        if actions:
            entry["can"].append("toggle")
    elif any(a.startswith(PRESS_WORDS) for a in actions):
        entry["can"].append("press")
    if _has(states, SELECTABLE) or kind in ("listitem", "tabitem", "treeitem", "dataitem"):
        entry["can"].append("select")
    if _has(states, EXPANDABLE) or any("expand" in a for a in actions):
        entry["can"].append("expand")
    if "org.a11y.atspi.EditableText" in ifaces and _has(states, EDITABLE):
        entry["can"].append("type")
    if role == "password text":
        entry["secret"] = True
    elif kind in ("edit", "combobox", "spinner") and "org.a11y.atspi.Text" in ifaces:
        entry["value"] = _text(ref)[:200]
    return entry


def _pid_of(bus_name: str) -> int | None:
    try:
        return int(_call(("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus",
                         "GetConnectionUnixProcessID", "s", (bus_name,))[0])
    except Exception:  # noqa: BLE001
        return None


def _window_ref(pid: int | None, title: str):
    """The accessibility node of a top-level window: the app with that
    process id (or any app, if sandboxing hides the id), then its frame with
    that title."""
    root = ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")
    apps = _children(root)
    by_pid = [a for a in apps if pid and _pid_of(a[0]) == pid]
    wanted = (title or "").strip().lower()
    best = None
    for app in by_pid + [a for a in apps if a not in by_pid]:
        for frame in _children(app):
            name = str(_prop(frame, ACC, "Name") or "").strip().lower()
            if name == wanted:
                return frame
            if wanted and best is None and (wanted in name or name in wanted) and name:
                best = frame
        if by_pid and app in by_pid and best is None:
            frames = _children(app)
            if len(frames) == 1:
                best = frames[0]
    return best


_refs: dict[int, list] = {}


def controls_sync(wid: int, limit: int = 250) -> list[dict]:
    from . import desktop_os, uia
    w = desktop_os.window(wid)
    if not w:
        raise AxError("That window is gone.")
    root = _window_ref(w.get("pid"), w["title"])
    if root is None:
        raise AxError("That window doesn't expose its controls to accessibility.")
    elements, entries, queue, seen = [], [], [root], 0
    while queue and len(entries) < limit and seen < MAX_NODES:
        ref = queue.pop(0)
        seen += 1
        entry = _entry(ref, len(elements))
        if entry and (entry["type"] in uia.ACTIONABLE or entry["type"] in uia.READABLE) and (entry["name"] or entry["can"]):
            elements.append(ref)
            entries.append(entry)
        queue.extend(_children(ref))
    _refs[int(wid)] = elements
    return entries


def _do_action(ref, words) -> bool:
    for i, name in enumerate(_actions(ref)):
        if any(name.startswith(w) or w in name for w in words):
            _call(ref, "org.a11y.atspi.Action", "DoAction", "i", (i,))
            return True
    return False


def act_on(ref, entry: dict, action: str, text: str | None) -> str:
    if action == "type":
        try:
            ok = _call(ref, "org.a11y.atspi.EditableText", "SetTextContents", "s", (text or "",))[0]
        except Exception as exc:  # noqa: BLE001
            raise AxError(f"{entry['type']} \"{entry['name']}\" does not take typed text.") from exc
        if not ok:
            raise AxError(f"{entry['type']} \"{entry['name']}\" refused the text.")
        return "set its value"
    words = {"press": PRESS_WORDS + ("toggle",), "toggle": ("toggle", "click", "press", "activate"),
             "select": ("select", "click", "activate", "press"), "expand": ("expand", "open", "click")}.get(action)
    if words is None:
        raise AxError(f"Unknown action {action!r}; use press, toggle, select, expand or type.")
    if _do_action(ref, words):
        return {"press": "pressed it", "toggle": "toggled it", "select": "selected it", "expand": "expanded it"}[action]
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
    node = elements[ref]
    entry = _entry(node, ref)
    if entry is None:
        raise AxError(f"Control {ref} is gone -- the window changed. Call app_controls again.")
    if not entry["enabled"]:
        raise AxError(f"{entry['type']} \"{entry['name']}\" is disabled.")
    if action == "type" and not replace:
        existing = "*" if entry.get("secret") and _text(node) else _text(node).strip()
        if existing:
            raise AxError(uia.REPLACE_REFUSAL.format(control=f"{entry['type']} \"{entry['name']}\"", chars=len(existing)))
    how = act_on(node, entry, action, text)
    return {"control": f"{entry['type']} \"{entry['name']}\"", "how": how, "rect": entry["rect"]}


def act_at_sync(x: int, y: int) -> dict | None:
    """Press whatever is at a screen point: find the window there, then the
    deepest control containing the point, walking up to one that presses."""
    from . import desktop_os
    try:
        w = desktop_os.window_at(x, y)
        node = _window_ref(w.get("pid"), w["title"]) if w else None
    except Exception:  # noqa: BLE001
        return None
    for _ in range(40):
        if node is None:
            return None
        try:
            child = tuple(_call(node, "org.a11y.atspi.Component", "GetAccessibleAtPoint", "iiu", (int(x), int(y), 0))[0])
        except Exception:  # noqa: BLE001
            child = None
        if not child or child[1] in ("/org/a11y/atspi/null", "") or child == node:
            break
        node = child
    for _ in range(4):
        if node is None:
            return None
        entry = _entry(node, 0)
        if entry and entry["enabled"] and any(v in entry["can"] for v in ("press", "toggle", "select", "expand")):
            try:
                how = act_on(node, entry, "press", None)
            except Exception:  # noqa: BLE001
                return None
            return {"control": f"{entry['type']} \"{entry['name']}\"", "how": how}
        try:
            parent = _prop(node, ACC, "Parent")
            node = tuple(parent) if parent else None
        except Exception:  # noqa: BLE001
            return None
    return None


def tree_summary(depth: int = 2) -> list:
    """Every app on the accessibility bus with its top-level nodes, for
    diagnosing "that window doesn't expose its controls"."""
    root = ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")

    def node(ref, level):
        try:
            role = str(_call(ref, ACC, "GetRoleName")[0])
        except Exception as exc:  # noqa: BLE001
            role = f"? ({exc})"
        states = _states(ref)
        item = {"role": role, "name": str(_prop(ref, ACC, "Name") or ""),
                "states": [i for i in range(64) if states >> i & 1],
                "ifaces": [i.rsplit(".", 1)[-1] for i in _interfaces(ref)]}
        if level < depth:
            item["children"] = [node(c, level + 1) for c in _children(ref)[:12]]
        return item

    return [dict(node(app, 0), pid=_pid_of(app[0])) for app in _children(root)]
