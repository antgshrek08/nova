import ast, asyncio, importlib.util, sys, types, unittest
from pathlib import Path
from unittest.mock import AsyncMock
ROOT=Path(__file__).resolve().parents[1]/'app'
pkg=types.ModuleType('roster_checks');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
for name in ('config','db'):
    stub=types.ModuleType('roster_checks.'+name);sys.modules[stub.__name__]=stub
spec=importlib.util.spec_from_file_location('roster_checks.teams',ROOT/'teams.py')
teams=importlib.util.module_from_spec(spec);sys.modules[spec.name]=teams;spec.loader.exec_module(teams)

def function(path,name,env):
    node=next(n for n in ast.parse((ROOT/path).read_text(encoding='utf-8')).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),path,'exec'),env)
    return env[name]

class RosterChecks(unittest.IsolatedAsyncioTestCase):
    def test_eight_teams_three_providers_six_roles(self):
        self.assertEqual(len(teams.ROLES),55)
        for team in teams.TEAM_LABELS:
            roles=[r for r in teams.ROLES.values() if r.team==team]
            self.assertEqual(len(roles),6)
            providers={r.default_model_id for r in roles}
            if team == 'everyday':
                self.assertEqual(providers, {'openrouter:openrouter/free'})
                self.assertTrue(all(not r.writes_files for r in roles))
                continue
            self.assertEqual(len(providers),3)
            self.assertIn('ollama:qwen3.5:4b',providers)
            self.assertTrue(all(sum(r.default_model_id==p for r in roles)==2 for p in providers))
        self.assertEqual(teams.ROLES['director'].default_model_id,'ollama:qwen3.5:4b')
        self.assertEqual(teams.ROLES['engineering:implementer'].default_model_id,'codex_cli')
        self.assertEqual(teams.ROLES['engineering:reviewer'].default_model_id,'claude_cli_plan')

    def test_capability_guards(self):
        status={'available':True}
        self.assertFalse(teams.role_availability(teams.ROLES['engineering:implementer'],'codex_cli_plan',status)['available'])
        self.assertFalse(teams.role_availability(teams.ROLES['research:researcher'],'claude_cli',status)['available'])
        self.assertTrue(teams.role_availability(teams.ROLES['research:reviewer'],'claude_cli_plan',status)['available'])

    async def test_openrouter_cannot_replace_director_or_specialists(self):
        with self.assertRaises(ValueError):
            await teams.set_role_override('director', 'openrouter:openrouter/free')
        with self.assertRaises(ValueError):
            await teams.set_role_override('engineering:reviewer', 'openrouter:openrouter/free')
        self.assertEqual(await teams.resolve_role_model_id('director'), teams.LOCAL_MODEL)

    def test_chat_director_cannot_delegate_to_everyday(self):
        validate=function('director.py','validate_decision',{'teams':teams})
        with self.assertRaisesRegex(RuntimeError, 'scheduled daily tasks'):
            validate({'delegate':True,'subtasks':[{'team':'everyday','role':'briefing','title':'Answer chat','depends_on':[]}]})

    def test_director_rejects_invalid_plans(self):
        validate=function('director.py','validate_decision',{'teams':teams})
        valid={'delegate':True,'subtasks':[{'team':'engineering','role':'implementer','title':'Implement','depends_on':[]},{'team':'engineering','role':'reviewer','title':'Review','depends_on':[0]}]}
        validate(valid)
        for bad in [[],{'delegate':'false'},{'delegate':True,'subtasks':[]},{'delegate':True,'subtasks':[{'team':'fake','role':'fake','title':'x'}]},{'delegate':True,'subtasks':[{'team':'engineering','role':'implementer','title':'x','depends_on':[0]}]}]:
            with self.assertRaises(RuntimeError):validate(bad)

    async def test_readonly_cli_commands(self):
        captured=[]
        async def stream(command,*args,**kwargs):captured.append(command);yield 'ok'
        from typing import AsyncIterator
        env={'AsyncIterator':AsyncIterator,'config':types.SimpleNamespace(CLAUDE_CLI_PATH='claude',CLAUDE_CLI_MODEL='',CODEX_CLI_PATH='codex',CODEX_CLI_MODEL=''),'_format_cli_transcript':lambda m:'prompt','_stream_cli':stream,'_claude_stream_text':(lambda chunks: chunks),'_record_cli_usage':AsyncMock(),'onyx_mcp_config':(lambda: None)}
        for name in ('stream_claude_cli','stream_codex_cli'):
            call=function('providers.py',name,env)
            self.assertEqual(''.join([c async for c in call([],read_only=True)]),'ok')
        self.assertIn('plan',captured[0]);self.assertIn('Read,Grep,Glob',captured[0])
        self.assertIn('read-only',captured[1]);self.assertNotIn('--approve-for-me',captured[1])

    def test_review_routes_share_subscription_budget(self):
        tree=ast.parse((ROOT/'team_usage.py').read_text())
        assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SUBSCRIPTIONS' for t in n.targets))
        env={};exec(compile(ast.Module(body=[assignment],type_ignores=[]),'budget','exec'),env)
        self.assertTrue({'claude_cli_plan','codex_cli_plan','antigravity_cli'} <= env['SUBSCRIPTIONS'])
