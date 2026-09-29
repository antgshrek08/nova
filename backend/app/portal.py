"""The desktop portal (xdg-desktop-portal): how an app asks a Wayland desktop
for things it doesn't let apps do directly. Nova uses it for screenshots.
GNOME asks the user once and remembers the answer; KDE and wlroots desktops
answer straight away.
"""
from __future__ import annotations

import os
import secrets
from urllib.parse import unquote, urlparse


def screenshot(timeout: float = 30.0) -> bytes | None:
    """PNG bytes of the whole screen, or None if the desktop said no."""
    from jeepney import DBusAddress, MatchRule, new_method_call
    from jeepney.bus_messages import message_bus
    from jeepney.io.blocking import open_dbus_connection

    with open_dbus_connection(bus="SESSION") as conn:
        token = "nova" + secrets.token_hex(6)
        sender = conn.unique_name[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=handle)
        conn.send_and_get_reply(message_bus.AddMatch(rule))
        with conn.filter(rule) as queue:
            portal = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop",
                                 interface="org.freedesktop.portal.Screenshot")
            conn.send_and_get_reply(new_method_call(portal, "Screenshot", "sa{sv}",
                                                    ("", {"handle_token": ("s", token), "interactive": ("b", False)})))
            signal = conn.recv_until_filtered(queue, timeout=timeout)
    response, results = signal.body
    if response != 0 or "uri" not in results:
        return None
    path = unquote(urlparse(results["uri"][1]).path)
    try:
        with open(path, "rb") as f:
            return f.read()
    finally:
        # The portal saves into the user's Pictures folder; this one was Nova's.
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------- keyboard
#
# Wayland keeps apps from typing into each other. The RemoteDesktop portal is
# the sanctioned way: the desktop shows its own "allow Nova to control the
# keyboard?" prompt once, and with persist_mode the answer is remembered
# (restore token), so later sessions start without asking again.

import threading

_kb_lock = threading.Lock()
_kb = {"conn": None, "session": None}
KEYBOARD = 1


def _request(conn, interface: str, method: str, signature: str, body: tuple, token: str, timeout: float = 120.0) -> dict:
    from jeepney import DBusAddress, MatchRule, new_method_call
    from jeepney.bus_messages import message_bus
    sender = conn.unique_name[1:].replace(".", "_")
    handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=handle)
    conn.send_and_get_reply(message_bus.AddMatch(rule))
    with conn.filter(rule) as queue:
        address = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop", interface=interface)
        conn.send_and_get_reply(new_method_call(address, method, signature, body))
        signal = conn.recv_until_filtered(queue, timeout=timeout)
    response, results = signal.body
    if response != 0:
        raise PermissionError("The desktop didn't allow Nova to use the keyboard.")
    return results


def _keyboard_session():
    """An approved RemoteDesktop session, reused while Nova runs."""
    if _kb["session"]:
        return _kb["conn"], _kb["session"]
    from jeepney.io.blocking import open_dbus_connection
    from . import operator_store
    conn = open_dbus_connection(bus="SESSION")
    iface = "org.freedesktop.portal.RemoteDesktop"
    t = "nova" + secrets.token_hex(6)
    created = _request(conn, iface, "CreateSession", "a{sv}",
                       ({"handle_token": ("s", t), "session_handle_token": ("s", "s" + t)},), t)
    session = created["session_handle"][1]
    saved = (operator_store.get("control", "wayland_keyboard") or {}).get("restore_token")
    options = {"handle_token": ("s", "d" + t), "types": ("u", KEYBOARD), "persist_mode": ("u", 2)}
    if saved:
        options["restore_token"] = ("s", saved)
    _request(conn, iface, "SelectDevices", "oa{sv}", (session, options), "d" + t)
    started = _request(conn, iface, "Start", "osa{sv}", (session, "", {"handle_token": ("s", "g" + t)}), "g" + t)
    token = started.get("restore_token", (None, None))[1]
    if token:
        operator_store.put("control", "wayland_keyboard", {"restore_token": token})
    _kb.update(conn=conn, session=session)
    return conn, session


def send_keysyms(steps: list[tuple[int, bool]]) -> None:
    """Press (True) and release (False) X keysyms, in order, through the portal."""
    from jeepney import DBusAddress, new_method_call
    with _kb_lock:
        conn, session = _keyboard_session()
        address = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop",
                              interface="org.freedesktop.portal.RemoteDesktop")
        for keysym, down in steps:
            conn.send_and_get_reply(new_method_call(address, "NotifyKeyboardKeysym", "oa{sv}iu",
                                                    (session, {}, int(keysym), 1 if down else 0)))
