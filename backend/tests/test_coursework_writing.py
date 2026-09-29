import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app import coursework, config, skills, operator_store as store
from app import agent_loop

URL = 'https://school.example/courses/12/assignments/34'

class WritingWorkflow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        p = patch.object(config, 'DB_PATH', Path(temp.name) / 'test.db')
        p.start(); self.addCleanup(p.stop)
        self.packet = {'url':URL,'title':'Research essay','assignment_id':'34','user_id':'7', 'instructions':'Write an essay',
                       'locked':False,'submission_types':['online_text_entry'],'allowed_extensions':[], 'essay':True}

    async def test_essay_needs_user_topic_approval_before_draft(self):
        with patch.object(coursework, 'assignment', AsyncMock(return_value=self.packet)):
            with self.assertRaisesRegex(ValueError, 'topic'):
                await coursework.prepare(URL, 'online_text_entry', text='Essay')

    async def test_approved_topic_still_requires_draft_review_before_submit(self):
        with patch.object(coursework, 'assignment', AsyncMock(return_value=self.packet)):
            proposal = await coursework.topic(URL, 'A focused topic', 'A researchable question')
            coursework.approve_topic(proposal['id'])
            draft = await coursework.prepare(URL, 'online_text_entry', text='Essay', sources=['https://example.org/source'])
        coursework.grant(URL, True, user_id=7)
        with patch.object(coursework, 'current_receipt', AsyncMock()) as receipt:
            with self.assertRaisesRegex(ValueError, 'review'):
                await coursework.submit(draft['id'])
            receipt.assert_not_called()

    def test_research_writing_keeps_tools(self):
        self.assertTrue(skills.writing_needs_tools('Write a research essay with sources'))
        self.assertTrue(skills.writing_needs_tools('Complete this assignment in Canvas'))
        self.assertFalse(skills.writing_needs_tools('Write a bedtime story'))

    def test_calendar_feed_links_resolve_to_assignment(self):
        self.assertEqual(coursework.assignment_location('https://school.example/calendar?include_contexts=course_12&month=08#assignment_34')[3], URL)

    async def test_old_topic_cannot_approve_replacement(self):
        with patch.object(coursework, 'assignment', AsyncMock(return_value=self.packet)):
            first = await coursework.topic(URL, 'First topic', 'First rationale')
            second = await coursework.topic(URL, 'Second topic', 'Second rationale')
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaisesRegex(ValueError, 'replaced'):
            coursework.approve_topic(first['id'])
        self.assertFalse(store.get('essay_topic', second['id'])['approved'])

    async def test_ambiguous_text_entry_requires_review(self):
        self.packet['essay'] = False
        self.packet['instructions'] = 'See attached instructions.'
        with patch.object(coursework, 'assignment', AsyncMock(return_value=self.packet)):
            draft = await coursework.prepare(URL, 'online_text_entry', text='Complete response')
        self.assertTrue(draft['review_required'])

    async def test_canvas_tools_keep_research_without_unrelated_roster(self):
        with patch.object(agent_loop.mcp_manager, 'cached_tools_for_chat', AsyncMock()) as mcp:
            schemas, _ = await agent_loop._collect_tools(True, 'Read my Canvas assignment and its sources')
        names = {s['function']['name'] for s in schemas}
        self.assertIn('coursework_material', names)
        self.assertIn('web_search', names)
        self.assertIn('run_python', names)
        self.assertNotIn('send_email', names)
        self.assertNotIn('delegate_to_agent', names)
        mcp.assert_not_called()
