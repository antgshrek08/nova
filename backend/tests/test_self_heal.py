"""Nova noticing and fixing bugs in its own code (app/self_heal.py)."""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import self_heal, sentinel

BROKEN = "def total(items):\n    return sum(item['price'] for item in itemz)\n"
FIXED = "def total(items):\n    return sum(item['price'] for item in items)\n"


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "backend/app").mkdir(parents=True)
    (root / "backend/app/cart.py").write_text(BROKEN, encoding="utf-8")
    with patch.object(sentinel, "get_repo_root", return_value=root), \
         patch.object(sentinel.config, "DB_PATH", tmp_path / "data/nova.db"), \
         patch.object(self_heal, "_enabled", return_value=True), \
         patch.object(self_heal, "_LOOP", None):
        sentinel._LAST_CHECKPOINT = None
        yield root


def _bug_record(root, error_type="NameError", line=2):
    tb = (
        "Traceback (most recent call last):\n"
        f'  File "{root / "backend/app/main.py"}", line 10, in chat\n'
        f'  File "{root / "backend/app/cart.py"}", line {line}, in total\n'
        f'  File "{root.parent / "site-packages/lib.py"}", line 5, in helper\n'
        f"{error_type}: name 'itemz' is not defined\n"
    )
    own_file, own_line = sentinel.own_frame(tb)
    return {"type": error_type, "message": "name 'itemz' is not defined", "traceback": tb,
            "source": "/chat", "own_file": own_file, "own_line": own_line}


def _coder(label="Claude"):
    return SimpleNamespace(label=label, provider="claude_cli_plan", model=None)


EDIT = (
    "FILE: backend/app/cart.py\n<<<<<<< FIND\n"
    "    return sum(item['price'] for item in itemz)\n=======\n"
    "    return sum(item['price'] for item in items)\n>>>>>>> REPLACE\n"
)


def test_the_last_frame_in_novas_own_code_is_blamed_not_the_library(source):
    record = _bug_record(source)
    assert (record["own_file"], record["own_line"]) == ("backend/app/cart.py", 2)


def test_errors_that_are_the_worlds_fault_are_not_treated_as_bugs(source):
    record = _bug_record(source, error_type="ConnectionError")
    assert self_heal.consider(record) is None
    assert self_heal.bugs() == []


def test_the_same_bug_is_remembered_once_and_counted(source):
    self_heal.consider(_bug_record(source))
    self_heal.consider(_bug_record(source))
    [bug] = self_heal.bugs()
    assert bug["count"] == 2
    assert bug["file"] == "backend/app/cart.py" and bug["status"] == "open"


def test_a_dismissed_bug_stays_dismissed(source):
    bug = self_heal.consider(_bug_record(source))
    assert self_heal.dismiss(bug["sig"])
    self_heal.consider(_bug_record(source))
    assert self_heal.bugs() == []


def test_edits_must_match_exactly_once_and_stay_in_the_engine(source):
    assert self_heal.apply_edits(self_heal.parse_edits(EDIT), source) == {"backend/app/cart.py": FIXED}
    with pytest.raises(ValueError, match="matched 0"):
        self_heal.apply_edits([("backend/app/cart.py", "nope", "x")], source)
    with pytest.raises(ValueError, match="engine code"):
        self_heal.apply_edits([("frontend/src/App.jsx", "a", "b")], source)
    with pytest.raises(ValueError, match="engine code"):
        self_heal.apply_edits([("backend/app/../../x.py", "a", "b")], source)


def test_a_fix_that_passes_the_tests_is_kept(source):
    bug = self_heal.consider(_bug_record(source))
    with patch.object(self_heal, "_coders", AsyncMock(return_value=[_coder()])), \
         patch("app.providers.run_model_call", AsyncMock(return_value=EDIT)), \
         patch.object(sentinel.selfcheck, "run_tests", AsyncMock(return_value={"ok": True, "passed": True})), \
         patch.object(self_heal, "_tell", AsyncMock()) as tell:
        result = asyncio.run(self_heal.repair(bug["sig"]))
    assert result["ok"], result
    assert (source / "backend/app/cart.py").read_text(encoding="utf-8") == FIXED
    assert self_heal.get(bug["sig"])["status"] == "fixed"
    assert "fixed" in tell.call_args.args[0]


def test_a_fix_that_breaks_a_test_is_undone(source):
    bug = self_heal.consider(_bug_record(source))
    with patch.object(self_heal, "_coders", AsyncMock(return_value=[_coder()])), \
         patch("app.providers.run_model_call", AsyncMock(return_value=EDIT)), \
         patch.object(sentinel.selfcheck, "run_tests", AsyncMock(return_value={"ok": True, "passed": False, "summary": "1 failed"})), \
         patch.object(self_heal, "_tell", AsyncMock()):
        result = asyncio.run(self_heal.repair(bug["sig"]))
    assert not result["ok"]
    assert (source / "backend/app/cart.py").read_text(encoding="utf-8") == BROKEN
    saved = self_heal.get(bug["sig"])
    assert saved["status"] == "open" and "undone" in saved["last_result"]


def test_the_next_model_gets_a_turn_when_the_first_has_no_fix(source):
    bug = self_heal.consider(_bug_record(source))
    calls = AsyncMock(side_effect=["NO FIX", EDIT])
    with patch.object(self_heal, "_coders", AsyncMock(return_value=[_coder("A"), _coder("B")])), \
         patch("app.providers.run_model_call", calls), \
         patch.object(sentinel.selfcheck, "run_tests", AsyncMock(return_value={"ok": True, "passed": True})), \
         patch.object(self_heal, "_tell", AsyncMock()):
        result = asyncio.run(self_heal.repair(bug["sig"]))
    assert result["ok"] and self_heal.get(bug["sig"])["fixed_by"] == "B"


def test_no_coding_model_is_said_plainly(source):
    bug = self_heal.consider(_bug_record(source))
    with patch.object(self_heal, "_coders", AsyncMock(return_value=[])):
        result = asyncio.run(self_heal.repair(bug["sig"]))
    assert not result["ok"] and "No coding model" in result["error"]


@pytest.mark.parametrize("mode,repairs,tells", [("ask", 0, 1), ("auto", 2, 0), ("off", 0, 0)])
def test_the_users_setting_decides_what_happens(source, mode, repairs, tells):
    bug = self_heal.consider(_bug_record(source))
    with patch.object(self_heal, "mode", AsyncMock(return_value=mode)), \
         patch.object(self_heal, "repair", AsyncMock()) as repair, \
         patch.object(self_heal, "_tell", AsyncMock()) as tell:
        asyncio.run(self_heal._follow_up(bug["sig"]))
        asyncio.run(self_heal._follow_up(bug["sig"]))  # asked once, not every time
    assert repair.await_count == repairs  # the mock records no attempt, so auto tries each time
    assert tell.await_count == tells


def test_errors_logged_by_background_work_reach_sentinel(source):
    handler = self_heal.ErrorLogHandler()
    log = logging.getLogger("app.some_background_job")
    log.addHandler(handler)
    try:
        with patch.object(sentinel, "record_error") as record:
            try:
                {}["missing"]
            except KeyError:
                log.exception("The job failed")
        assert record.call_count == 1
        assert isinstance(record.call_args.args[1], KeyError)
    finally:
        log.removeHandler(handler)


def test_record_error_hands_novas_own_bugs_to_self_heal(source):
    try:
        exec(compile("itemz", str(source / "backend/app/cart.py"), "exec"), {})
    except NameError as exc:
        record = sentinel.record_error("/chat", exc)
    assert record["own_file"] == "backend/app/cart.py"
    assert [b["sig"] for b in self_heal.bugs()] == [self_heal.signature(record)]


def test_a_read_only_install_says_so_instead_of_trying(source):
    bug = self_heal.consider(_bug_record(source))
    with patch("app.self_heal.os.access", return_value=False):
        result = asyncio.run(self_heal.repair(bug["sig"]))
    assert not result["ok"] and "can't change its own files" in result["error"]
