"""The autonomy gate has to cover the tools that actually exist.

MUTATING_TOOLS decides what needs approval at `guarded` and what is refused
outright at `readonly`. It is a hand-maintained set of names, checked against
nothing, which is exactly the shape of thing that rots: it listed "close_app",
a tool that has never existed, while the real close_window went ungated. A
gate naming a tool that is not there looks identical to a gate that works.

So these tests check the set against the registry instead of against intent.
"""
import unittest

from app import nova_tools


REGISTERED = {t["function"]["name"] for t in nova_tools.TOOL_SCHEMAS}

# Tools that are read-only on purpose. Listing them here means a new tool is
# never silently ungated: it is either mutating, or a deliberate entry below.
KNOWN_READ_ONLY = {
    'coursework_read', 'coursework_status', 'coursework_list',
    "calendar_events", "calendar_list", "canvas_assignments", "homework_assignments", "calendar_agenda", "calendar_free_time", "expand_result",
    "desktop_read_screen", "desktop_screenshot", "focus_window", "get_clipboard",
    "glob_files", "grep_files", "list_agents", "list_dir", "list_processes",
    "list_secrets", "list_windows", "process_output", "read_file", "self_check",
    "watch_video", "web_fetch", "web_search",
    # Rewrites only Nova's own generated calendar file, never the user's data.
    "canvas_sync",
    # Reading Nova's own mailbox changes nothing: the IMAP session is opened
    # readonly, so not even the seen flag moves. send_email is the gated
    # counterpart -- it leaves the machine and cannot be recalled.
    "check_email", "email_verification_code",
    # Metadata about accounts the user set up: service, username, which address
    # it was registered to. Never a password -- those live in the vault, and
    # signing in goes through type_secret, which is gated.
    "my_accounts",
    # Downloads a clip to a temp folder, reads it, deletes it. Nothing the
    # user can see changes, and the file does not outlive the call. The
    # sign-in it may trigger on a login wall is gated in its own right.
    "watch_reel",
    # Dispatches to watch_reel, the vision model or web_fetch, all of which
    # are read-only, and ends in a question. Nothing it can reach changes
    # anything the user can see.
    "look_at",
    # Read a window's accessibility tree, or capture what it paints. Nothing
    # changes; app_click / app_type are the gated counterparts.
    "app_controls", "window_screenshot",
}


class GateMatchesTheRegistry(unittest.TestCase):
    def test_the_gate_names_no_tool_that_does_not_exist(self):
        """A phantom entry gates nothing and hides that it gates nothing."""
        phantoms = sorted(set(nova_tools.MUTATING_TOOLS) - REGISTERED)
        self.assertEqual(phantoms, [], f"gated but not registered: {phantoms}")

    def test_every_tool_is_either_gated_or_known_read_only(self):
        """A new tool cannot slip in ungated without someone deciding."""
        unclassified = sorted(REGISTERED - set(nova_tools.MUTATING_TOOLS) - KNOWN_READ_ONLY)
        self.assertEqual(
            unclassified, [],
            "these tools are neither gated nor listed as read-only -- decide which: "
            f"{unclassified}",
        )

    def test_the_read_only_list_has_no_stale_names(self):
        stale = sorted(KNOWN_READ_ONLY - REGISTERED)
        self.assertEqual(stale, [], f"read-only list names missing tools: {stale}")


class ThingsThatMustNeverBeUngated(unittest.TestCase):
    """Named individually, because each was or could be a real hole."""

    def test_closing_a_window_needs_approval(self):
        """It can discard unsaved work, and it is what close_app meant."""
        self.assertIn("close_window", nova_tools.MUTATING_TOOLS)

    def test_delegating_to_an_external_agent_needs_approval(self):
        """Claude Code and Codex have their own file tools. Ungated, this was
        the way around every other entry: Nova would ask before writing a file
        and not before asking another agent to write one."""
        self.assertIn("delegate_to_agent", nova_tools.MUTATING_TOOLS)

    def test_starting_a_process_needs_approval_however_it_is_started(self):
        for name in ("start_process", "stop_process", "preview_server", "run_command"):
            self.assertIn(name, nova_tools.MUTATING_TOOLS, name)

    def test_writing_to_the_users_real_calendar_needs_approval(self):
        for name in ("calendar_create_event", "calendar_delete_event"):
            self.assertIn(name, nova_tools.MUTATING_TOOLS, name)

    def test_readonly_refuses_everything_mutating(self):
        for name in sorted(nova_tools.MUTATING_TOOLS):
            self.assertTrue(nova_tools.refused_by_autonomy(name, "readonly"), name)
            self.assertFalse(nova_tools.refused_by_autonomy(name, "full"), name)

    def test_guarded_asks_for_everything_mutating(self):
        for name in sorted(nova_tools.MUTATING_TOOLS):
            self.assertTrue(nova_tools.needs_approval(name, "guarded"), name)
            self.assertEqual(nova_tools.needs_approval(name, "full"), name in nova_tools.operator_tools.CONFIRMED, name)

    def test_reading_is_never_gated(self):
        for name in sorted(KNOWN_READ_ONLY):
            self.assertFalse(nova_tools.needs_approval(name, "guarded"), name)
            self.assertFalse(nova_tools.refused_by_autonomy(name, "readonly"), name)


if __name__ == "__main__":
    unittest.main()
