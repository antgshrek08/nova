import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import agent_loop, vision
from app import operator_tools


class ImageToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_screenshot_reaches_next_model_call(self):
        seen=[]
        async def stream(result,messages,schemas):
            seen.append(list(messages))
            if len(seen)==1:
                yield ('calls',[{'id':'shot','function':{'name':'desktop_screenshot','arguments':'{}'}}])
            else:
                yield ('token','Image read')
                yield ('calls',[])
        async def announce(*args): pass
        result=SimpleNamespace(provider='ollama',model='qwen3.5:4b',label='Qwen')
        with patch.object(agent_loop,'_stream_once',stream), \
             patch.object(agent_loop,'_run_tool',AsyncMock(return_value={'ok':True,'result':{},'_image':'cG5n'})), \
             patch.object(agent_loop,'_announce',announce):
            events=[e async for e in agent_loop._run_with_tools(result,[{'role':'user','content':'Read the screen'}],[],{},'full')]
        self.assertTrue(vision.has_images(seen[1]))
        self.assertTrue(any(e['type']=='screenshot' for e in events))
    def test_submission_capability_is_application_fact(self):
        for question in ('can you submit assignments for me?', 'can nova automatically submit my assignments?', 'are you able to submit assignments on my behalf?'):
            self.assertEqual(operator_tools.capability_answer(question), operator_tools.SUBMISSION_CAPABILITY)
        self.assertIsNone(operator_tools.capability_answer('Submit my assignment now'))
        self.assertIsNone(operator_tools.capability_answer('Can you submit assignments for me and delete the drafts?'))

    async def check_route(self, model, expected):
        called = []

        async def tool_stream(*args):
            called.append('tools')
            yield {'type': 'token', 'content': 'inspected'}

        async def plain_stream(*args):
            called.append('plain')
            yield {'type': 'token', 'content': 'described'}

        candidate = SimpleNamespace(provider='ollama', model=model, label=model)
        messages = [{'role': 'user', 'content': vision.build_content('Inspect this', [{'data': b'fixture'}])}]
        with patch.object(agent_loop.nova_tools, 'autonomy_level', AsyncMock(return_value='full')), \
             patch.object(agent_loop, '_collect_tools', AsyncMock(return_value=([{'function': {'name': 'desktop_screenshot'}}], {}))), \
             patch.object(agent_loop, '_run_with_tools', tool_stream), \
             patch.object(agent_loop, '_stream_plain', plain_stream), \
             patch.object(agent_loop, '_local_fallback', plain_stream):
            events = [e async for e in agent_loop.run([candidate], messages)]
        self.assertEqual(called, expected)
        return events

    async def test_screenshot_keeps_qwen_tools(self):
        await self.check_route('qwen3.5:4b', ['tools'])

    async def test_gemma_image_does_not_receive_unsupported_tools(self):
        await self.check_route('gemma3:4b', ['plain'])

    async def test_blind_candidate_and_fallback_never_receive_image(self):
        events = await self.check_route('qwen2.5-coder:7b', [])
        self.assertTrue(any(e.get('type') == 'reroute' for e in events))
