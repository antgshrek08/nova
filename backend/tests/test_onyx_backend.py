"""Nova driving Onyx: the client, the target translation, and the routing.

Onyx itself is faked at the HTTP layer (httpx.MockTransport) or at
onyx.call; the live end-to-end run against a real Onyx build is recorded in
the Onyx repo's agent-surface spec.
"""
import asyncio
import json

import httpx
import pytest

from app import browser_control, onyx


@pytest.fixture(autouse=True)
def _no_real_settings(monkeypatch):
    # perform() reads the visibility setting; the real read opens Nova's
    # shared settings connection, whose thread would outlive these tests.
    async def hidden():
        return "hidden"
    monkeypatch.setattr(browser_control, "visibility", hidden)


# --------------------------------------------------------------- targets

@pytest.mark.parametrize("selector,expected", [
    ("12", {"ref": 12}),
    ("[12]", {"ref": 12}),
    ("ref=7", {"ref": 7}),
    ("text=Sign in", {"text": "Sign in"}),
    ('text="Sign in"', {"text": "Sign in"}),
    ("#login > button", {"selector": "#login > button"}),
    ("x=340.5,y=212", {"x": 340.5, "y": 212.0}),
    ("x=-12,y=8", {"x": -12.0, "y": 8.0}),
    ("", {}),
    (None, {}),
])
def test_target_translation(selector, expected):
    assert onyx.target(selector) == expected


def test_describe_elements_gives_a_graph_the_pixel_math():
    text = onyx.describe_elements([
        {"ref": 5, "role": "img", "name": "graph paper", "box": {"x": 322, "y": 10, "width": 500, "height": 500},
         "graph": {"xMin": -8, "xMax": 8, "yMin": -8, "yMax": 8}},
    ])
    assert "axis x:-8..8 y:-8..8" in text
    assert "pixel x=572,y=260" in text  # data (0,0): centered in an 8..-8 box
    assert "browser_act using selector/to=\"x=<px>,y=<py>\"" in text


def test_describe_elements_never_shows_a_secret_value():
    lines = onyx.describe_elements([
        {"ref": 0, "role": "textbox", "name": "Email", "value": "a@b.c"},
        {"ref": 1, "role": "textbox", "name": "Password", "secret": True},
        {"ref": 2, "role": "checkbox", "name": "Remember", "checked": True},
        {"ref": 3, "role": "link", "name": "Far", "inViewport": False},
    ])
    assert '[0] textbox "Email" = "a@b.c"' in lines
    assert "[1] textbox \"Password\" (secret field" in lines
    assert "[checked]" in lines and "(off screen)" in lines


# --------------------------------------------------------------- endpoint file

def test_endpoint_path_points_at_novas_own_profile_not_the_users():
    # Found live: Onyx pausing itself when the user took over the main
    # window's mouse stalled Nova's task for a "press Resume" they might not
    # see for a while. Nova's own profile (see Onyx's nova-window.ts) is a
    # second, always-hidden window the user never touches, so that pause can
    # never happen against Nova -- but only if Nova actually talks to that
    # window's agent server, not the main one's.
    assert onyx.endpoint_path().name == "agent-endpoint-nova.json"


def test_read_endpoint_requires_loopback_and_a_live_onyx(tmp_path, monkeypatch):
    path = tmp_path / "agent-endpoint.json"
    good = {"url": "http://127.0.0.1:5000/mcp", "token": "t" * 64, "pid": 4242, "version": "0.1.0"}
    monkeypatch.setattr(onyx, "_pid_alive", lambda pid: pid == 4242)

    path.write_text(json.dumps(good))
    assert onyx.read_endpoint(path) == good

    path.write_text(json.dumps({**good, "url": "http://evil.test:5000/mcp"}))
    assert onyx.read_endpoint(path) is None, "the token must never go anywhere but loopback"

    path.write_text(json.dumps({**good, "pid": 1}))
    assert onyx.read_endpoint(path) is None, "a crashed Onyx's file points at a port someone else may own"

    path.write_text("{not json")
    assert onyx.read_endpoint(path) is None


# --------------------------------------------------------------- the wire

@pytest.fixture
def fake_onyx(monkeypatch):
    """An Onyx at the HTTP layer that records requests and answers tools/call."""
    seen: list[dict] = []
    replies: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"headers": dict(request.headers), "body": body})
        if request.headers.get("authorization") != "Bearer " + "t" * 64:
            return httpx.Response(401)
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}})
        name = body["params"]["name"]
        result = replies.get(name, {"content": [{"type": "text", "text": "{}"}]})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    monkeypatch.setattr(onyx, "_transport", httpx.MockTransport(handler))
    endpoint = {"url": "http://127.0.0.1:5000/mcp", "token": "t" * 64, "pid": 1, "version": "x"}
    monkeypatch.setattr(onyx, "read_endpoint", lambda path=None: endpoint)
    return seen, replies


def test_call_sends_the_key_and_names_itself(fake_onyx):
    seen, replies = fake_onyx
    replies["tabs_list"] = {"content": [{"type": "text", "text": json.dumps([{"id": "tab-1"}])}]}
    assert asyncio.run(onyx.call("tabs_list")) == [{"id": "tab-1"}]
    call = seen[-1]
    assert call["headers"]["authorization"] == "Bearer " + "t" * 64
    assert call["headers"]["x-agent-name"] == "Nova"
    assert call["body"]["params"] == {"name": "tabs_list", "arguments": {}}


def test_call_passes_onyx_refusals_through_in_its_own_words(fake_onyx):
    _, replies = fake_onyx
    replies["click"] = {"isError": True, "content": [{"type": "text", "text": "Paused: You took over."}]}
    with pytest.raises(onyx.OnyxError, match="You took over"):
        asyncio.run(onyx.call("click", ref=3))


def test_call_returns_screenshots_as_images(fake_onyx):
    _, replies = fake_onyx
    replies["page_screenshot"] = {"content": [{"type": "image", "data": "iVBOR", "mimeType": "image/png"}]}
    assert asyncio.run(onyx.call("page_screenshot")) == {"_image": "iVBOR"}


def test_call_drops_unset_arguments(fake_onyx):
    seen, _ = fake_onyx
    asyncio.run(onyx.call("navigate", url="https://a.test/", tabId=None))
    assert seen[-1]["body"]["params"]["arguments"] == {"url": "https://a.test/"}


# --------------------------------------------------------------- starting Onyx

def test_ensure_says_plainly_when_onyx_is_not_installed(monkeypatch):
    monkeypatch.setattr(onyx, "read_endpoint", lambda path=None: None)
    monkeypatch.setattr(onyx, "find_exe", lambda configured="": None)
    with pytest.raises(onyx.OnyxUnavailable, match="not installed"):
        asyncio.run(onyx.ensure())


def test_ensure_launches_onyx_in_the_background_and_waits_for_its_port(monkeypatch, tmp_path):
    exe = tmp_path / "Onyx.exe"
    exe.write_text("")
    launched = []
    endpoint = {"url": "http://127.0.0.1:5000/mcp", "token": "t" * 64, "pid": 1}
    state = {"up": False}

    def launch(path):
        launched.append(path)
        state["up"] = True

    async def ping(ep):
        return True

    monkeypatch.setattr(onyx, "find_exe", lambda configured="": exe)
    monkeypatch.setattr(onyx, "_launch", launch)
    monkeypatch.setattr(onyx, "_ping", ping)
    monkeypatch.setattr(onyx, "read_endpoint", lambda path=None: endpoint if state["up"] else None)
    assert asyncio.run(onyx.ensure()) == endpoint
    assert launched == [exe]


# --------------------------------------------------------------- browser_act routing

@pytest.fixture
def onyx_calls(monkeypatch):
    """Route browser_control to a scripted Onyx and record every tool call."""
    calls: list[tuple[str, dict]] = []
    tabs = {"open": []}

    async def fake_call(tool, configured_path="", **args):
        calls.append((tool, args))
        if tool == "tab_open":
            tab_id = f"tab-{len(tabs['open']) + 10}"
            tabs["open"].append(tab_id)
            return {"id": tab_id, "url": args.get("url") or ""}
        if tool == "tabs_list":
            return [{"id": t} for t in tabs["open"]] + [{"id": "users-tab"}]
        if tool == "page_read":
            return {"url": "https://a.test/", "title": "A", "text": "hello",
                    "elements": [{"ref": 0, "role": "button", "name": "Go"}]}
        if tool == "click":
            return {"clicked": 'button "Go"', "urlBefore": "x", "urlAfter": "x"}
        if tool == "type":
            return {"typed": len(args.get("text", "")), "into": 'input "Email"'}
        if tool == "drag":
            return {"from": {"x": args["from"].get("x"), "y": args["from"].get("y")},
                    "to": {"x": args["to"].get("x"), "y": args["to"].get("y")}}
        return {}

    async def backend():
        return "onyx", ""

    browser_control._onyx_tabs.clear()
    monkeypatch.setattr(onyx, "call", fake_call)
    monkeypatch.setattr(browser_control, "_backend", backend)
    return calls, tabs


def test_first_navigation_opens_novas_own_tab_at_the_url(onyx_calls):
    calls, _ = onyx_calls
    result = asyncio.run(browser_control.perform("navigate", url="https://a.test/"))
    assert calls[0] == ("tab_open", {"url": "https://a.test/"})
    assert not any(tool == "navigate" for tool, _ in calls), "no second load of the same page"
    assert result["browser"] == "onyx"
    assert '[0] button "Go"' in result["page"]


def test_later_actions_stay_in_novas_tab_and_never_touch_the_users(onyx_calls):
    calls, _ = onyx_calls
    asyncio.run(browser_control.perform("navigate", url="https://a.test/"))
    asyncio.run(browser_control.perform("navigate", url="https://b.test/"))
    asyncio.run(browser_control.perform("click", selector="0"))
    targeted = [args.get("tabId") for tool, args in calls if "tabId" in args]
    assert targeted and set(targeted) == {"tab-10"}
    assert ("navigate", {"url": "https://b.test/", "tabId": "tab-10"}) in calls
    assert ("click", {"tabId": "tab-10", "ref": 0}) in calls


def test_a_tab_the_user_closed_is_replaced_not_reused(onyx_calls):
    calls, tabs = onyx_calls
    asyncio.run(browser_control.perform("navigate", url="https://a.test/"))
    tabs["open"].clear()  # the user closed it
    asyncio.run(browser_control.perform("inspect"))
    assert [tool for tool, _ in calls].count("tab_open") == 2


def test_drag_sends_pixel_points_for_a_graph(onyx_calls):
    calls, _ = onyx_calls
    result = asyncio.run(browser_control.perform("drag", selector="x=572,y=260", to="x=822,y=10"))
    tool, args = next(c for c in calls if c[0] == "drag")
    assert args == {"tabId": "tab-10", "from": {"x": 572.0, "y": 260.0}, "to": {"x": 822.0, "y": 10.0}}
    assert result["dragged"] == {"from": {"x": 572.0, "y": 260.0}, "to": {"x": 822.0, "y": 10.0}}


def test_drag_needs_both_a_from_and_a_to(onyx_calls):
    with pytest.raises(ValueError, match="drag needs"):
        asyncio.run(browser_control.perform("drag", selector="0"))
    with pytest.raises(ValueError, match="drag needs"):
        asyncio.run(browser_control.perform("drag", to="x=1,y=1"))


def test_fill_by_label_uses_onyxs_into_and_replaces_what_is_there(onyx_calls):
    calls, _ = onyx_calls
    result = asyncio.run(browser_control.perform("fill", selector="text=Email", text="a@b.c"))
    tool, args = next(c for c in calls if c[0] == "type")
    assert args == {"tabId": "tab-10", "text": "a@b.c", "clear": True, "into": "Email"}
    assert result["filled"] == 'input "Email"'


def test_click_without_a_selector_is_refused_before_anything_moves(onyx_calls):
    calls, _ = onyx_calls
    with pytest.raises(ValueError, match="needs a selector"):
        asyncio.run(browser_control.perform("click"))
    assert not any(tool == "click" for tool, _ in calls)


def test_navigation_still_refuses_non_web_urls(onyx_calls):
    with pytest.raises(ValueError, match="HTTP"):
        asyncio.run(browser_control.perform("navigate", url="file:///C:/Windows/win.ini"))


def test_falls_back_to_edge_and_says_so_when_onyx_is_missing(monkeypatch):
    async def backend():
        return "onyx", ""

    async def unavailable(*a, **k):
        raise onyx.OnyxUnavailable("Onyx is not installed")

    async def edge(*a, **k):
        return {"url": "https://a.test/", "title": "A"}

    monkeypatch.setattr(browser_control, "_backend", backend)
    monkeypatch.setattr(browser_control, "_perform_onyx", unavailable)
    monkeypatch.setattr(browser_control, "_perform_edge", edge)
    result = asyncio.run(browser_control.perform("navigate", url="https://a.test/"))
    assert result["browser"] == "edge"
    assert "not installed" in result["note"]


def test_falls_back_to_edge_when_onyx_is_paused_for_a_takeover(monkeypatch):
    # Found live: the user took over Onyx's mouse/keyboard, Onyx paused itself
    # (as it should -- see Onyx's AgentController.pause), and Nova just gave
    # up and asked them to click Resume rather than doing anything else. That
    # pause is a deliberate stop, not a bug, so nothing here should try to
    # click past it -- but Nova's own separate Edge window isn't the window
    # they're using, so the task can carry on there instead of stalling.
    async def backend():
        return "onyx", ""

    async def paused(*a, **k):
        raise onyx.OnyxError("Paused: You took over. Resume when you want the assistant to carry on.")

    async def edge(*a, **k):
        return {"url": "https://a.test/", "title": "A"}

    monkeypatch.setattr(browser_control, "_backend", backend)
    monkeypatch.setattr(browser_control, "_perform_onyx", paused)
    monkeypatch.setattr(browser_control, "_perform_edge", edge)
    result = asyncio.run(browser_control.perform("click", selector="0"))
    assert result["browser"] == "edge"
    assert "paused" in result["note"].lower()
    assert "Onyx was left alone" in result["note"]


def test_a_non_pause_onyx_error_is_not_swallowed_by_the_edge_fallback(monkeypatch):
    # The Edge fallback exists for "Onyx is unreachable" (missing/paused),
    # not for "Onyx told me something went wrong" -- a stale ref or a failed
    # click is real information the model should read and act on in Onyx
    # itself, not something to quietly paper over with a different browser.
    async def backend():
        return "onyx", ""

    async def stale(*a, **k):
        raise onyx.OnyxError("ref 12 is stale -- the page changed; read it again")

    async def edge(*a, **k):
        raise AssertionError("must not fall back to Edge for an ordinary Onyx error")

    monkeypatch.setattr(browser_control, "_backend", backend)
    monkeypatch.setattr(browser_control, "_perform_onyx", stale)
    monkeypatch.setattr(browser_control, "_perform_edge", edge)
    with pytest.raises(onyx.OnyxError, match="stale"):
        asyncio.run(browser_control.perform("click", selector="12"))


def test_edge_backend_setting_bypasses_onyx(monkeypatch):
    async def backend():
        return "edge", ""

    async def boom(*a, **k):
        raise AssertionError("Onyx must not be used when the setting says edge")

    async def edge(*a, **k):
        return {"url": "https://a.test/"}

    monkeypatch.setattr(browser_control, "_backend", backend)
    monkeypatch.setattr(browser_control, "_perform_onyx", boom)
    monkeypatch.setattr(browser_control, "_perform_edge", edge)
    result = asyncio.run(browser_control.perform("navigate", url="https://a.test/"))
    assert result["url"] == "https://a.test/" and "visibility" in result


def test_hover_glides_onto_the_target_without_clicking(onyx_calls):
    calls, _ = onyx_calls
    asyncio.run(browser_control.perform("hover", selector="text=Account"))
    assert ("hover", {"tabId": "tab-10", "text": "Account"}) in calls
    assert not any(tool == "click" for tool, _ in calls)


def test_find_exe_prefers_the_configured_path_then_the_newest_build(tmp_path, monkeypatch):
    import os
    old = tmp_path / "installed" / "Onyx.exe"
    new = tmp_path / "dev" / "Onyx.exe"
    for p in (old, new):
        p.parent.mkdir()
        p.write_text("")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    monkeypatch.setattr(onyx, "exe_candidates", lambda configured="": [old, new])
    assert onyx.find_exe() == new, "an old install without agent control would look like a hang"
    assert onyx.find_exe(str(old)) == old, "a path the user set always wins"


def test_inspect_carries_page_text_so_a_click_result_is_visible(onyx_calls):
    result = asyncio.run(browser_control.perform("inspect"))
    assert result["page"].startswith("Text:\nhello")
    assert '[0] button "Go"' in result["page"]


def test_toggle_reaches_onyx_only_when_asked(onyx_calls):
    # Found live: on Canvas the "mark as done" checkbox shares the assignment's
    # name. Onyx refuses on/off controls unless the click says toggle=True.
    calls, _ = onyx_calls
    asyncio.run(browser_control.perform("navigate", url="https://a.test/"))
    asyncio.run(browser_control.perform("click", selector="0"))
    asyncio.run(browser_control.perform("click", selector="0", toggle=True))
    clicks = [args for tool, args in calls if tool == "click"]
    assert "toggle" not in clicks[0]
    assert clicks[1]["toggle"] is True


def test_browser_act_tells_the_model_about_on_off_controls():
    from app import nova_tools
    spec = next(t for t in nova_tools.TOOL_SCHEMAS if t["function"]["name"] == "browser_act")
    fn = spec.get("function") or spec
    assert "mark as done" in fn["description"]
    assert "toggle" in fn["parameters"]["properties"]


def test_edge_supports_coordinate_drag(monkeypatch):
    from unittest.mock import AsyncMock
    from app import browser_cursor
    class Tab:
        url = 'https://fixture.test'
        title = AsyncMock(return_value='Fixture')
        wait_for_timeout = AsyncMock()
    tab = Tab()
    drag = AsyncMock()
    monkeypatch.setattr(browser_control, 'page', AsyncMock(return_value=tab))
    monkeypatch.setattr(browser_control, '_snapshot', AsyncMock(return_value={'title': 'Fixture'}))
    monkeypatch.setattr(browser_cursor, 'drag_and_drop', drag)
    asyncio.run(browser_control._perform_edge('drag', selector='x=1,y=2', to='x=3,y=4'))
    drag.assert_awaited_once_with(tab, 1.0, 2.0, 3.0, 4.0)


def test_edge_fallback_refuses_on_off_controls_too(monkeypatch):
    from app import browser_cursor
    async def click_element(page, target):
        await target.click()
    monkeypatch.setattr(browser_cursor, 'click_element', click_element)
    clicked = []

    class Target:
        async def evaluate(self, js):
            assert "checkbox" in js
            return True
        async def click(self):
            clicked.append(True)

    class Locator:
        first = Target()

    class Tab:
        url = 'https://fixture.test'
        async def title(self):
            return 'Fixture'
        def locator(self, selector):
            return Locator()
        async def wait_for_timeout(self, ms):
            pass

    async def page():
        return Tab()

    monkeypatch.setattr(browser_control, "page", page)
    with pytest.raises(ValueError, match="mark.*assignment done|marking an assignment done"):
        asyncio.run(browser_control._perform_edge("click", selector="#done"))
    assert clicked == []
    try:
        asyncio.run(browser_control._perform_edge("click", selector="#done", toggle=True))
    except Exception:
        pass  # the page read after the click is not faked; the click itself is what matters
    assert clicked == [True]


def test_math_boxes_and_frame_controls_are_marked_for_the_model():
    line = onyx.describe_elements([{"ref": 42, "role": "textbox", "name": "Response input area", "math": True, "frame": "www.knewton.com", "value": "17"}])
    assert "(math box" in line and "(in www.knewton.com)" in line and '= "17"' in line


def test_the_knewton_routine_is_picked_for_homework_requests():
    from app import skills
    skills.reload_skills()
    msg = "Open canvas and do all open calculus homework from 3.3b to 3.9c. each assignment do problems until you reach 100% mastery on each."
    chosen = [s.name for s in skills.select_relevant_skills(msg)]
    assert chosen[0] == "knewton-alta"
    body = next(s for s in skills.all_skills() if s.name == "knewton-alta").body
    assert "Brainfuse" in body and "SUBMIT" in body


def test_claude_gets_onyx_tools_only_when_onyx_is_open(monkeypatch, tmp_path):
    import json as _json
    from app import providers
    monkeypatch.setattr(onyx, "read_endpoint", lambda path=None: None)
    assert providers.onyx_mcp_config() is None
    monkeypatch.setattr(onyx, "read_endpoint", lambda path=None: {"url": "http://127.0.0.1:5555/mcp", "token": "t0k", "pid": 1})
    cfg = providers.onyx_mcp_config()
    try:
        server = _json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["onyx"]
        assert server == {"type": "http", "url": "http://127.0.0.1:5555/mcp",
                          "headers": {"Authorization": "Bearer t0k", "X-Agent-Name": "Nova"}}
    finally:
        cfg.unlink(missing_ok=True)
