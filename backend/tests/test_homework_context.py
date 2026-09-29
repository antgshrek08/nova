import json
import unittest
from unittest.mock import AsyncMock, patch
from app import homework_context as context, coursework_browser


class ContextTests(unittest.TestCase):
    def test_compact_preserves_question_math_and_live_controls(self):
        result = {'session_id':'abc','snapshot':'def','frames':[
            {'url':'https://school/courses/1/assignments/2','text':'Canvas navigation','controls':[]},
            {'url':'https://alta.example','text':'Differentiate x^2','math':['x^2'],
             'controls':[{'ref':'7','name':'Answer','editable':True,'value':'2x','secret':False}]}]}
        reduced = context.compact(result)
        self.assertEqual(len(reduced['frames']),1)
        self.assertEqual(reduced['frames'][0]['math'],['x^2'])
        self.assertEqual(reduced['frames'][0]['controls'][0]['value'],'2x')
        self.assertEqual(len(result['frames']),2)

    def test_old_snapshots_removed_but_errors_and_latest_retained(self):
        rows = [{'role':'tool','content':json.dumps({'session_id':'s','snapshot':str(i),'frames':[]})} for i in range(4)]
        rows.append({'role':'tool','content':'{"error":"Stop"}'})
        context.trim_snapshots(rows)
        self.assertNotIn('frames',json.loads(rows[0]['content']))
        self.assertEqual(json.loads(rows[3]['content'])['snapshot'],'3')
        self.assertIn('Stop',rows[4]['content'])

    def test_long_run_keeps_valid_recent_tool_pairs_and_original_request(self):
        rows=[{'role':'user','content':'original request'}]
        for i in range(10):
            rows += [{'role':'assistant','tool_calls':[{'id':str(i)}]},
                     {'role':'tool','tool_call_id':str(i),'content':json.dumps({'assignment_url':'https://school/assignment','session_id':'s','frames':[{'text':'100% mastery'}]})}]
        context.trim_rounds(rows)
        self.assertEqual(rows[0]['content'],'original request')
        self.assertIn('100% mastery',rows[1]['content'])
        self.assertEqual(len([m for m in rows if m['role']=='tool']),6)
        self.assertEqual(rows[2]['tool_calls'][0]['id'],'4')



class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_knewton_has_the_onyx_browser_tool(self):
        from app import agent_loop
        tools, _ = await agent_loop._collect_tools(True, 'Complete Knewton calculus 3.3b to 100% mastery')
        names = {t['function']['name'] for t in tools}
        self.assertIn('browser_act', names)
        self.assertIn('coursework_external', names)
        self.assertIn('coursework_autopilot', names)

    async def test_include_submitted_omits_unsubmitted_filter(self):
        read = AsyncMock(side_effect=[{'id':7},[{'id':12,'name':'Calculus'}],[]])
        with patch.object(coursework_browser.coursework,'read_json',read), patch.object(coursework_browser.workflows,'require_running'):
            await coursework_browser.assignments('https://school.example',include_submitted=True)
        self.assertNotIn('bucket=unsubmitted',read.call_args.args[1])
