import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from playwright.async_api import async_playwright
from app import coursework_external as external, coursework, config, nova_tools

URL='https://school.example/courses/1/assignments/2'
PAGE='<iframe src="https://homework.example/problem"></iframe>'
PROBLEM='''<h1>Find the derivative of x squared</h1><math><msup><mi>x</mi><mn>2</mn></msup></math>
<input aria-label="Answer"><button onclick="document.querySelector('h1').innerText='Correct. Next question';window.submitted=true">Submit answer</button>'''


class ExternalHomework(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches=[patch.object(config,'DB_PATH',Path(self.tmp.name)/'test.db'),
                      patch.object(coursework,'read_json',AsyncMock(return_value={'id':7})),
                      patch.object(coursework,'assignment',AsyncMock(return_value={'url':URL,'title':'3.3b','locked':False,'submission_types':['external_tool'],'user_id':'7'}))]
        for p in self.patches: p.start();self.addCleanup(p.stop)
        self.driver=await async_playwright().start()
        self.browser=await self.driver.chromium.launch(headless=True)
        self.tab=await self.browser.new_page()
        await self.tab.route('https://school.example/**',lambda r:r.fulfill(body=PAGE,content_type='text/html'))
        await self.tab.context.route('https://homework.example/**',lambda r:r.fulfill(body=PROBLEM,content_type='text/html'))
        p=patch.object(external.browser_control,'page',AsyncMock(return_value=self.tab));p.start();self.addCleanup(p.stop)
        self.state=await external.perform('open',url=URL)

    async def asyncTearDown(self):
        external._sessions.clear()
        await self.browser.close()
        await self.driver.stop()

    def control(self,state,name):
        return next(c['ref'] for f in state['frames'] for c in f.get('controls',[]) if c['name']==name)

    def args(self,state,name):
        return dict(session_id=state['session_id'],snapshot=state['snapshot'],ref=self.control(state,name))

    async def test_reads_cross_origin_math_and_fills(self):
        frame=next(f for f in self.state['frames'] if 'homework.example' in f['url'])
        self.assertIn('derivative',frame['text'])
        self.assertIn('<msup>', ''.join(frame['math']))
        state=await external.perform('fill',text='2x',**self.args(self.state,'Answer'))
        self.assertEqual(await self.tab.frames[1].locator('input').input_value(),'2x')
        answer = next(c for f in state['frames'] for c in f.get('controls',[]) if c['name']=='Answer')
        self.assertEqual(answer['value'],'2x')
        with self.assertRaisesRegex(ValueError,'Stale'):
            await external.perform('fill',text='3x',**self.args(self.state,'Answer'))
        self.assertNotEqual(state['snapshot'],self.state['snapshot'])

    async def test_fill_dispatches_math_editor_keyboard_events(self):
        await self.tab.frames[1].locator('input').evaluate("e=>e.addEventListener('keydown',()=>{window.keyEvents=(window.keyEvents||0)+1})")
        await external.perform('fill',text='-12x^(-5/2)',**self.args(self.state,'Answer'))
        self.assertGreater(await self.tab.frames[1].evaluate('window.keyEvents'),5)

    async def test_type_appends_and_cannot_type_enter(self):
        state=await external.perform('fill',text='2',**self.args(self.state,'Answer'))
        state=await external.perform('type',text='x',**self.args(state,'Answer'))
        self.assertEqual(await self.tab.frames[1].locator('input').input_value(),'2x')
        with self.assertRaisesRegex(ValueError,'single-line'):
            await external.perform('type',text='\n',**self.args(state,'Answer'))

    async def test_ordinary_click_cannot_submit(self):
        with self.assertRaisesRegex(ValueError,'external_submit'):
            await external.perform('click',**self.args(self.state,'Submit answer'))
        self.assertFalse(await self.tab.frames[1].evaluate('Boolean(window.submitted)'))
        self.assertTrue(nova_tools.needs_approval('coursework_external_submit','full'))
        self.assertTrue(nova_tools.refused_by_autonomy('coursework_external_submit','readonly'))

    async def test_changed_question_refused(self):
        await self.tab.frames[1].locator('h1').evaluate("e=>e.innerText='Different question'")
        with self.assertRaisesRegex(ValueError,'question or feedback changed'):
            await external.perform('fill',text='2x',**self.args(self.state,'Answer'))

    async def test_secret_field_values_are_not_returned(self):
        await self.tab.frames[1].locator('body').evaluate('''e=>e.innerHTML='<input type="password" aria-label="Password" value="hidden-password"><input autocomplete="one-time-code" aria-label="OTP" value="123456">' ''')
        state = await external.perform('inspect',session_id=self.state['session_id'])
        for frame in state['frames']:
            for control in frame.get('controls',[]):
                if control['name'] in ('Password','OTP'):
                    self.assertIsNone(control['value'])

    async def test_submit_records_feedback(self):
        state=await external.perform('fill',text='2x',**self.args(self.state,'Answer'))
        result=await external.submit(answer='2x',reasoning='Power rule: d(x^2)/dx=2x.',**self.args(state,'Submit answer'))
        self.assertEqual(result['attempt']['status'],'feedback_changed')
        self.assertIn('Correct', result['attempt']['feedback'])

    async def test_account_switch_blocks_action(self):
        with patch.object(coursework,'read_json',AsyncMock(return_value={'id':8})):
            with self.assertRaisesRegex(ValueError,'account changed'):
                await external.perform('fill',text='2x',**self.args(self.state,'Answer'))

    async def test_follows_noopener_publisher_tab(self):
        await self.tab.frames[1].locator('body').evaluate("e=>e.innerHTML='<a href=\"https://homework.example/next\" target=\"_blank\" rel=\"noopener\">Launch assignment</a>'")
        state=await external.perform('inspect',session_id=self.state['session_id'])
        result=await external.perform('click',**self.args(state,'Launch assignment'))
        self.assertTrue(any(f['url']=='https://homework.example/next' for f in result['frames']))
        self.assertIsNot(external._sessions[state['session_id']]['tab'],self.tab)

    async def test_tracks_automatic_popup_during_open(self):
        await self.tab.unroute('https://school.example/**')
        page=PAGE+'<script>window.open("https://homework.example/automatic", "_blank")</script>'
        await self.tab.route('https://school.example/**',lambda r:r.fulfill(body=page,content_type='text/html'))
        state=await external.perform('open',url=URL)
        self.assertTrue(any(f['url']=='https://homework.example/automatic' for f in state['frames']))
        self.assertNotIn(self.state['session_id'],external._sessions)

    async def test_unknown_attempt_cannot_replay(self):
        await self.tab.frames[1].locator('button').evaluate("e=>e.onclick=()=>{window.submitted=true}")
        state=await external.perform('inspect',session_id=self.state['session_id'])
        result=await external.submit(answer='2x',reasoning='Power rule',**self.args(state,'Submit answer'))
        self.assertEqual(result['attempt']['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'recorded attempt'):
            await external.submit(answer='2x',reasoning='Power rule',**self.args(result,'Submit answer'))

    async def test_smartbook_confidence_submission_and_selected_answer(self):
        html = '''<h1>Question Mode: Consumer price responsiveness?</h1>
<label><input type="radio" name="answer">Price elasticity of demand</label>
<p>Rate your confidence to submit your answer.</p>
<button aria-label="High Confidence" onclick="document.querySelector('h1').innerText='Correct answer'">High</button>'''
        await self.tab.context.route('https://learning.mheducation.com/**', lambda r:r.fulfill(body=html,content_type='text/html'))
        await self.tab.goto('https://learning.mheducation.com/question')
        state = await external.perform('inspect',session_id=self.state['session_id'])
        state = await external.perform('click',**self.args(state,'Price elasticity of demand'))
        choice = next(c for f in state['frames'] for c in f['controls'] if c['type']=='radio')
        self.assertTrue(choice['checked'])
        with self.assertRaisesRegex(ValueError,'external_submit'):
            await external.perform('click',**self.args(state,'High Confidence'))
        result = await external.submit(answer='Price elasticity of demand',reasoning='Measures quantity demanded responsiveness to price.',**self.args(state,'High Confidence'))
        self.assertIn('Correct answer', result['attempt']['feedback'])

    def test_confidence_requires_publisher_and_submission_context(self):
        info = {'name':'High Confidence'}
        text = 'Rate your confidence to submit your answer.'
        self.assertFalse(external.submission_control(info,'https://other.example',text))
        self.assertFalse(external.submission_control(info,'https://mheducation.com.attacker.example',text))
        self.assertFalse(external.submission_control(info,'https://learning.mheducation.com','Choose display quality'))

    def test_correct_answer_does_not_increment_concept_progress(self):
        result = external.smartbook_feedback([{'url':'https://learning.mheducation.com/question',
            'text':'0 of 26 Concepts completed\nYour Answer correct'}])
        self.assertEqual(result['concepts_completed'],0)
        self.assertEqual(result['concepts_total'],26)
        self.assertEqual(result['answer_outcome'],'correct')
