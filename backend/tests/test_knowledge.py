"""What Nova keeps from a conversation, and what it refuses to keep.

The memory graph already gained a node per message, which is a transcript.
These tests cover the layer that makes it accumulate: distilled statements
that become their own nodes (see knowledge.py, graph._knowledge_layer).

The rule worth guarding hardest is provenance. memory.classify_fact_status
established that an assistant statement is not automatically a fact about the
user, however fact-shaped it sounds; this is the same rule at a second site,
and it is the one that would do real harm if it silently regressed -- a
memory that promotes the model's guesses into confirmed facts about a person
is worse than no memory at all.
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# An isolated database file: these tests write, and must never touch the real
# ~/.ai-council/ai_council.db the app is using.
#
# Setting os.environ["DB_PATH"] is NOT enough and was actively wrong. config.py
# reads that variable once, at import, and binds config.DB_PATH from it -- so
# in a full-suite run an alphabetically earlier test module has already
# imported config and pinned it to the real database. This file passed on its
# own and wrote four rows into the live database when run as part of the suite.
# Patch the resolved value instead, and drop any connection already opened
# against the real path so the next get_connection() reconnects here.
_TEMP_DIR = tempfile.TemporaryDirectory()

from app import config  # noqa: E402

_REAL_DB_PATH = config.DB_PATH
config.DB_PATH = Path(_TEMP_DIR.name) / "test.db"

from app import db, graph, knowledge  # noqa: E402  -- must follow the patch

_REAL_CONNECTION = db._connection
db._connection = None


def run(coro):
    return asyncio.run(coro)


class Isolation(unittest.IsolatedAsyncioTestCase):
    async def test_these_tests_write_to_a_temp_database(self):
        """Guards the bug this file caused once: an env-var override applied
        after config.py had already been imported did nothing, and the suite
        wrote fixture rows into the user's live database."""
        await db.get_connection()
        cursor = await db._connection.execute("PRAGMA database_list")
        in_use = Path([dict(zip([c[0] for c in cursor.description], r))
                       for r in await cursor.fetchall()][0]["file"])
        self.assertEqual(in_use.resolve(), Path(config.DB_PATH).resolve())
        self.assertNotEqual(in_use.resolve(), Path(_REAL_DB_PATH).resolve())
        self.assertIn(Path(_TEMP_DIR.name).resolve(), in_use.resolve().parents)


class Parsing(unittest.TestCase):
    def test_json_wrapped_in_prose_is_still_read(self):
        """Small local models routinely add a sentence or a code fence."""
        raw = 'Sure! {"facts":[{"subject":"A","statement":"A long enough statement.","from":"user"}]} done'
        self.assertEqual(len(knowledge._parse(raw)), 1)

    def test_unparseable_output_yields_nothing(self):
        for raw in ("", "no json at all", "{broken", "[]", None):
            self.assertEqual(knowledge._parse(raw), [])

    def test_fingerprint_ignores_case_spacing_and_punctuation(self):
        self.assertEqual(
            knowledge.fingerprint("The user is taking MAC2311 this semester."),
            knowledge.fingerprint("  the user is   taking mac2311 this semester  "),
        )

    def test_fingerprint_keeps_different_statements_apart(self):
        self.assertNotEqual(
            knowledge.fingerprint("The user is taking MAC2311."),
            knowledge.fingerprint("The user is taking ECO2023."),
        )


class Provenance(unittest.TestCase):
    def test_user_assertions_are_confirmed(self):
        cleaned = knowledge._clean(
            {"subject": "Courses", "statement": "The user is taking MAC2311.", "from": "user"}
        )
        self.assertEqual(cleaned["status"], "confirmed")
        self.assertEqual(cleaned["source_role"], "user")

    def test_assistant_statements_are_never_confirmed(self):
        cleaned = knowledge._clean(
            {"subject": "Calculus", "statement": "The chain rule handles composite functions.",
             "from": "assistant"}
        )
        self.assertEqual(cleaned["status"], "unconfirmed")

    def test_an_unrecognised_source_is_treated_as_the_assistant(self):
        """The safe direction. A malformed "from" must never mint a fact
        about the user out of something the model produced."""
        cleaned = knowledge._clean(
            {"subject": "X", "statement": "Something plausible sounding.", "from": "weird"}
        )
        self.assertEqual(cleaned["source_role"], "assistant")
        self.assertEqual(cleaned["status"], "unconfirmed")

    def test_junk_is_dropped(self):
        for bad in (
            {"subject": "", "statement": "No subject was given."},
            {"subject": "Has subject", "statement": "tiny"},
            {"subject": "x" * 200, "statement": "A perfectly fine statement."},
            {"subject": "ok", "statement": "y" * 500},
            "not a dict",
            None,
        ):
            self.assertIsNone(knowledge._clean(bad), bad)

    def test_unknown_category_falls_back_to_fact(self):
        cleaned = knowledge._clean(
            {"subject": "X", "statement": "A statement worth keeping.",
             "category": "nonsense", "from": "user"}
        )
        self.assertEqual(cleaned["category"], "fact")


class Storage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.get_connection()
        conn = await db.get_connection()
        await conn.execute("DELETE FROM knowledge")
        await conn.commit()
        self.conversation = await db.create_conversation("chat")

    def _fact(self, statement, status="confirmed", role="user", subject="Courses"):
        return {
            "conversation_id": self.conversation["id"],
            "message_id": None,
            "subject": subject,
            "statement": statement,
            "category": "schedule",
            "status": status,
            "source_role": role,
            "fingerprint": knowledge.fingerprint(statement),
        }

    async def test_a_statement_is_stored_once_however_often_it_is_relearned(self):
        """The same fact comes up across months of chats. That must deepen
        one node, not grow a pile of near-identical ones."""
        await db.upsert_knowledge(self._fact("The user is taking MAC2311."))
        await db.upsert_knowledge(self._fact("the user is taking mac2311"))
        rows = await db.list_knowledge()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["times_seen"], 2)

    async def test_the_user_can_confirm_something_the_assistant_said(self):
        await db.upsert_knowledge(
            self._fact("The user prefers dark themes.", status="unconfirmed", role="assistant")
        )
        await db.upsert_knowledge(
            self._fact("The user prefers dark themes.", status="confirmed", role="user")
        )
        rows = await db.list_knowledge()
        self.assertEqual(rows[0]["status"], "confirmed")
        self.assertEqual(rows[0]["source_role"], "user")

    async def test_a_confirmed_fact_is_never_demoted_by_the_assistant(self):
        """The reverse direction must not happen: Nova repeating something
        back cannot downgrade what the user actually said."""
        await db.upsert_knowledge(
            self._fact("The user is taking ECO2023.", status="confirmed", role="user")
        )
        await db.upsert_knowledge(
            self._fact("The user is taking ECO2023.", status="unconfirmed", role="assistant")
        )
        rows = await db.list_knowledge()
        self.assertEqual(rows[0]["status"], "confirmed")
        self.assertEqual(rows[0]["source_role"], "user")

    async def test_a_correction_is_confirmed_and_rejects_duplicates(self):
        wrong = await db.upsert_knowledge(self._fact("The user is taking MAC2312.", status="unconfirmed", role="assistant"))
        await db.upsert_knowledge(self._fact("The user prefers dark themes."))
        fixed = await db.update_knowledge(wrong["id"], "The user is taking MAC2311.", knowledge.fingerprint("The user is taking MAC2311."))
        self.assertEqual((fixed["statement"], fixed["status"], fixed["source_role"]), ("The user is taking MAC2311.", "confirmed", "user"))
        with self.assertRaises(ValueError):
            await db.update_knowledge(wrong["id"], "The user prefers dark themes.", knowledge.fingerprint("The user prefers dark themes."))
        self.assertIsNone(await db.update_knowledge(999999, "Anything at all.", knowledge.fingerprint("Anything at all.")))

    async def test_deleting_removes_it(self):
        row = await db.upsert_knowledge(self._fact("The user uses three monitors."))
        self.assertTrue(await db.delete_knowledge(row["id"]))
        self.assertEqual(await db.list_knowledge(), [])


class GraphLayer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        conn = await db.get_connection()
        await conn.execute("DELETE FROM knowledge")
        await conn.commit()
        self.conversation = await db.create_conversation("chat")

    async def _store(self, subject, statement):
        return await db.upsert_knowledge({
            "conversation_id": self.conversation["id"],
            "message_id": None,
            "subject": subject,
            "statement": statement,
            "category": "fact",
            "status": "confirmed",
            "source_role": "user",
            "fingerprint": knowledge.fingerprint(statement),
        })

    async def test_each_statement_becomes_a_node_linked_to_its_conversation(self):
        await self._store("Courses", "The user is taking MAC2311.")
        nodes, edges = await graph._knowledge_layer()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["kind"], "knowledge")
        self.assertEqual(nodes[0]["label"], "Courses")
        self.assertIn(
            {"source": nodes[0]["id"], "target": f"conversation-{self.conversation['id']}",
             "kind": "explicit", "relation": "learned_in"},
            edges,
        )

    async def test_statements_about_one_subject_are_chained_not_fully_connected(self):
        """A subject with many statements would otherwise contribute O(n^2)
        edges and dominate the layout for no extra information."""
        for i in range(4):
            await self._store("Courses", f"The user is enrolled in course number {i}00.")
        _, edges = await graph._knowledge_layer()
        same_subject = [e for e in edges if e.get("relation") == "same_subject"]
        self.assertEqual(len(same_subject), 3)  # chained: n-1, not n*(n-1)/2

    async def test_different_subjects_are_not_linked_to_each_other(self):
        await self._store("Courses", "The user is taking MAC2311.")
        await self._store("Monitors", "The user runs three monitors.")
        _, edges = await graph._knowledge_layer()
        self.assertEqual([e for e in edges if e.get("relation") == "same_subject"], [])

    async def test_node_carries_provenance_so_the_ui_can_tell_them_apart(self):
        await db.upsert_knowledge({
            "conversation_id": self.conversation["id"], "message_id": None,
            "subject": "Guess", "statement": "Something Nova worked out itself.",
            "category": "fact", "status": "unconfirmed", "source_role": "assistant",
            "fingerprint": knowledge.fingerprint("Something Nova worked out itself."),
        })
        nodes, _ = await graph._knowledge_layer()
        self.assertEqual(nodes[0]["status"], "unconfirmed")


class Extraction(unittest.IsolatedAsyncioTestCase):
    async def test_trivial_messages_are_not_sent_to_a_model_at_all(self):
        """Extraction runs on every chat, so 'thanks' must cost nothing."""
        with mock.patch.object(knowledge, "available_model") as model:
            self.assertEqual(await knowledge.extract("thanks!", "You're welcome."), [])
            model.assert_not_called()

    async def test_no_local_model_means_no_learning_and_no_paid_call(self):
        with mock.patch.object(knowledge, "available_model", return_value=None), \
             mock.patch.object(knowledge.providers, "stream_ollama") as streamed:
            result = await knowledge.extract("A message long enough to be worth extracting from.", "Reply.")
        self.assertEqual(result, [])
        streamed.assert_not_called()

    async def test_a_model_failure_is_swallowed(self):
        """Nova failing to learn must never become Nova failing to answer."""
        async def boom(*args, **kwargs):
            raise RuntimeError("ollama is down")
            yield  # pragma: no cover -- makes this an async generator

        with mock.patch.object(knowledge, "available_model", return_value="qwen3.5:4b"), \
             mock.patch.object(knowledge.providers, "stream_ollama", boom):
            result = await knowledge.extract("A message long enough to be worth extracting from.", "Reply.")
        self.assertEqual(result, [])

    async def test_output_is_capped_and_deduplicated(self):
        facts = ",".join(
            f'{{"subject":"S{i}","statement":"Statement number {i} that is long enough.","from":"user"}}'
            for i in range(12)
        )
        duplicate = '{"subject":"S0","statement":"Statement number 0 that is long enough.","from":"user"}'

        async def reply(*args, **kwargs):
            yield '{"facts":[' + facts + "," + duplicate + "]}"

        with mock.patch.object(knowledge, "available_model", return_value="qwen3.5:4b"), \
             mock.patch.object(knowledge.providers, "stream_ollama", reply):
            result = await knowledge.extract("A message long enough to be worth extracting from.", "Reply.")
        self.assertEqual(len(result), knowledge.MAX_PER_EXCHANGE)
        self.assertEqual(len({f["fingerprint"] for f in result}), len(result))


def tearDownModule():
    # Windows will not delete an open file, and db keeps one shared connection
    # for the life of the process. Close it if we can; the temp directory is
    # the OS's to reclaim either way, so a failure here must not fail the run.
    async def _close():
        if db._connection is not None:
            await db._connection.close()

    try:
        run(_close())
    except Exception:  # noqa: BLE001
        pass
    # Hand the real database back to whatever runs after this module, or every
    # later test in the suite quietly inherits the temp one.
    db._connection = _REAL_CONNECTION
    config.DB_PATH = _REAL_DB_PATH
    try:
        _TEMP_DIR.cleanup()
    except Exception:  # noqa: BLE001
        pass  # Windows keeps a lock briefly; the OS reclaims temp either way


if __name__ == "__main__":
    unittest.main()
