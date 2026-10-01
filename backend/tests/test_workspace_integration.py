"""No real DB, providers or inference: regression tests for the actual code."""
import ast, asyncio, importlib.util, sys, types, unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
ROOT=Path(__file__).resolve().parents[1]/"app"
PKG="nova_checks"
package=types.ModuleType(PKG);package.__path__=[str(ROOT)];sys.modules[PKG]=package
for name in ("agents","classifier","code_files","config","db","providers","routing","teams"):
    mod=types.ModuleType(f"{PKG}.{name}");sys.modules[mod.__name__]=mod;setattr(package,name,mod)
def load(name):
    spec=importlib.util.spec_from_file_location(f"{PKG}.{name}",ROOT/f"{name}.py")
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod
director=load("director")
# Loaded for real rather than stubbed: vision.py imports only base64, and its
# answers ("does this turn carry images", "can that provider see them") steer
# which branch chat() takes. A stub would make the test green while testing a
# path no image ever travels.
vision=load("vision")


async def _fake_agent_loop_run(candidates,messages,**kwargs):
    """Stands in for agent_loop.run: one meta event then a short answer, which
    is the shape chat() consumes."""
    first=next(iter(candidates),None)
    yield {"type":"meta","provider":getattr(first,"provider","openrouter"),
           "model":getattr(first,"model","m"),"label":getattr(first,"label","Test"),
           "category":"everyday","custom_model_row_id":None,"rerouted":False,"attempts":[]}
    yield {"type":"token","content":"streamed answer"}
llm=types.ModuleType("litellm");llm.acompletion=AsyncMock()
with patch.dict(sys.modules,{"litellm":llm}): local=load("local_inference")

class Checks(unittest.IsolatedAsyncioTestCase):
    async def test_direct_team_answer_prefers_small_local_without_probe(self):
        package.classifier.classify=lambda _: 'quick_simple'
        package.routing.get_category_overrides=AsyncMock(return_value={})
        package.teams.assignment_statuses=AsyncMock(return_value={'ollama:qwen3.5:4b':{'available':True},'ollama:ornith:9b':{'available':True}})
        package.teams.require_available=AsyncMock()
        result=types.SimpleNamespace(provider='ollama',model='qwen3.5:4b',label='Qwen')
        package.providers.run_model_call=AsyncMock(return_value='Local answer')
        async def guarded(provider,fn):return await fn()
        with patch.object(director,'_resolve_team_model',AsyncMock(return_value=result)) as resolve,patch.object(director,'_run_guarded',guarded):
            await director._run_direct(self.rows[1])
        resolve.assert_awaited_once_with('ollama:qwen3.5:4b','quick_simple')
        self.assertEqual(self.rows[1]['status'],'done')

    async def test_exhausted_budget_is_visible_and_does_not_launch_worker(self):
        self.rows[2]=dict(id=2,parent_id=1,team='engineering',role='tester',description='Run tests',status='queued')
        package.teams.get_role=lambda *args:types.SimpleNamespace(key='engineering:tester',label='Tester',system_prompt='Test',writes_files=True)
        package.teams.resolve_role_model_id=AsyncMock(return_value='codex_cli')
        package.teams.require_available=AsyncMock()
        package.providers.ProviderRateLimitedError=type('RateLimited',(Exception,),{})
        package.providers.run_model_call=AsyncMock()
        async def guarded(provider,fn):return await fn()
        result=types.SimpleNamespace(provider='codex_cli',model=None,label='Codex')
        with patch.object(director,'_resolve_team_model',AsyncMock(return_value=result)),patch.object(director,'_run_guarded',guarded),patch.object(director.team_usage,'reserve',AsyncMock(side_effect=RuntimeError('Subscription task budget reached'))):
            self.assertFalse(await director._run_subtask(2))
        self.assertEqual(self.rows[2]['status'],'error')
        self.assertIn('budget reached',self.rows[2]['error'])
        package.providers.run_model_call.assert_not_called()

    async def test_specialist_budget_is_shared_and_persistent(self):
        events=[]
        package.db.get_task_activity=AsyncMock(side_effect=lambda _:list(events))
        async def record(tid,kind,message):events.append(dict(kind=kind,message=message))
        package.db.add_task_activity=record
        budget=director.team_usage
        budget._admission=asyncio.Lock()
        outcomes=await asyncio.gather(*(budget.reserve(1,'codex_cli',[{'content':'x'}]) for _ in range(3)),return_exceptions=True)
        self.assertEqual(sum(isinstance(o,RuntimeError) for o in outcomes),1)
        self.assertEqual(len(events),2)
        budget._admission=asyncio.Lock()  # simulated process-local state loss
        with self.assertRaisesRegex(RuntimeError,'budget reached'):
            await budget.reserve(1,'claude_cli',[{'content':'retry'}])

    async def test_local_does_not_spend_subscription_allowance(self):
        package.db.get_task_activity=AsyncMock()
        await director.team_usage.reserve(1,'ollama',[{'content':'x'}])
        package.db.get_task_activity.assert_not_called()

    async def test_oversized_specialist_context_is_not_sent(self):
        with self.assertRaisesRegex(RuntimeError,'24,000'):
            await director.team_usage.reserve(1,'codex_cli',[{'content':'x'*24001}])
        package.db.add_task_activity.assert_not_called()

    async def test_team_resolution_does_not_probe_subscription(self):
        package.routing.RoutingResult=lambda *args:types.SimpleNamespace(provider=args[1],model=args[2])
        package.routing.resolve_model_id=AsyncMock()
        result=await director._resolve_team_model('claude_cli:sonnet','review')
        self.assertEqual((result.provider,result.model),('claude_cli','sonnet'))
        package.routing.resolve_model_id.assert_not_called()

    async def test_gemini_stays_disabled_without_verified_login(self):
        gemini=load('gemini_cli')
        with patch.dict('os.environ',{'NOVA_GEMINI_CLI_VERIFIED':'0'}):
            self.assertFalse(gemini.availability()['available'])
            with self.assertRaises(RuntimeError):gemini.command()

    async def test_gemini_never_inherits_api_credentials(self):
        gemini=load('gemini_cli')
        env=gemini.environment({'PATH':'keep','GEMINI_API_KEY':'secret','GOOGLE_API_KEY':'secret','GOOGLE_GENAI_USE_VERTEXAI':'true'})
        self.assertEqual(env['PATH'],'keep')
        self.assertNotIn('GEMINI_API_KEY',env)
        self.assertNotIn('GOOGLE_API_KEY',env)
        self.assertNotIn('GOOGLE_GENAI_USE_VERTEXAI',env)
        self.assertEqual(env['GOOGLE_GENAI_USE_GCA'],'true')

    async def asyncSetUp(self):
        self.rows={1:dict(id=1,parent_id=None,status="running",description="Research and review",title="Root")}
        self.messages=[];self.deps={}
        async def get(tid):return self.rows.get(tid)
        async def update(tid,**kw):self.rows[tid].update(kw);return self.rows[tid]
        async def create(**kw):
            tid=max(self.rows)+1;self.rows[tid]=dict(id=tid,status="queued",**kw);return self.rows[tid]
        async def listing(parent_id=None):return [r for r in self.rows.values() if r.get("parent_id")==parent_id]
        async def add_dep(tid,dep):self.deps.setdefault(tid,[]).append(dep)
        async def deps(tid):return self.deps.get(tid,[])
        async def message(cid,role,content,**kw):
            m=dict(id=len(self.messages)+1,role=role,content=content,created_at="2026-09-09");self.messages.append(m);return m
        db=package.db
        db.get_task=get;db.update_task=update;db.create_task=create;db.list_tasks=listing
        db.add_task_activity=AsyncMock();db.add_task_dependency=add_dep;db.get_task_dependencies=deps
        db.get_app_settings=AsyncMock(return_value={});db.set_app_settings=AsyncMock()
        db.get_conversation=AsyncMock(return_value={"project_id":None});db.list_messages=AsyncMock(return_value=[])
        db.add_message=message;db.touch_conversation=AsyncMock()
        package.agents.registry=types.SimpleNamespace(broadcast_task=AsyncMock(),create_job=AsyncMock(return_value=types.SimpleNamespace(id=1)),update_job=AsyncMock(),append_output=AsyncMock())
        package.teams.get_role=lambda *a:types.SimpleNamespace(writes_files=False)
        director._running_tasks.clear();local._slot=asyncio.Semaphore(1)

    async def test_partial_missing_and_blocked(self):
        self.rows[2]=dict(id=2,title="Good",status="done",result_summary="Evidence")
        self.rows[3]=dict(id=3,title="Blocked",status="blocked")
        await director._synthesize(self.rows[1],[2,3,999])
        self.assertEqual(self.rows[1]["status"],"partial");self.assertIn("missing",self.rows[1]["result_summary"])
    async def test_total_failure(self):
        self.rows[2]=dict(id=2,title="Bad",status="error",error="Unavailable")
        await director._synthesize(self.rows[1],[2]);self.assertEqual(self.rows[1]["status"],"error")
    async def test_all_done(self):
        self.rows[2]=dict(id=2,title="Good",status="done")
        await director._synthesize(self.rows[1],[2]);self.assertEqual(self.rows[1]["status"],"done")
    async def test_cycle_is_not_success(self):
        await director._run_delegated(self.rows[1],[dict(team="research",role="researcher",title="A",depends_on=[1]),dict(team="research",role="researcher",title="B",depends_on=[0])])
        self.assertEqual(self.rows[1]["status"],"error")
    async def test_intent_gate(self):
        for text in ["Research this and review the findings","Build the page then test it"]:
            self.assertTrue(director.should_consider_delegation(text))
        for text in ["What is a reactor?","What is delegation?","Do not delegate; build and test this"]:
            self.assertFalse(director.should_consider_delegation(text))
    async def test_cancel_cascades(self):
        entered=asyncio.Event()
        async def worker(tid):entered.set();await asyncio.Event().wait()
        decision={"delegate":True,"subtasks":[dict(team="research",role="researcher",title="A")]}
        with patch.object(director,"_decide",AsyncMock(return_value=decision)),patch.object(director,"_run_subtask",worker):
            task=asyncio.create_task(director.run_root_task(1));await entered.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(all(r["status"]=="cancelled" for r in self.rows.values()))
    async def test_chat_streams_through_agent_loop_and_persists_one_reply(self):
        node=next(n for n in ast.parse((ROOT/"main.py").read_text(encoding="utf-8-sig")).body if isinstance(n,ast.AsyncFunctionDef) and n.name=="chat")
        node.decorator_list=[]
        # Every global `chat` reads must exist here, not just the ones the
        # delegation path happens to execute: an `except providers.X` clause
        # is evaluated while an exception propagates, so a missing name turns
        # into a NameError that masks the real assertion. Derived by walking
        # chat()'s AST for Load-context names rather than by trial and error,
        # so adding a new dependency to chat() fails loudly here instead of
        # silently skipping this regression test.
        async def _no_handoff(*a,**k):
            return
            yield  # noqa: unreachable -- makes this an async generator
        env=dict(ChatRequest=object,db=package.db,memory=types.SimpleNamespace(add_message=AsyncMock(),search=AsyncMock(return_value=[]),recall_for_chat=AsyncMock(return_value=[])),agents=package.agents,
            classifier=types.SimpleNamespace(classify=lambda _:"research",
                                             classify_async=AsyncMock(return_value="research")),skills=types.SimpleNamespace(select_relevant_skills=lambda _:[]),
            handoff_intent=types.SimpleNamespace(detect_handoff_intent=lambda _:None),director=director,NOVA_PERSONA_INSTRUCTIONS="Nova",
            _build_self_awareness_context=AsyncMock(return_value=""),_to_ndjson=lambda d:d,StreamingResponse=lambda it,**kw:it,
            _sync_conversation_note=AsyncMock(),_sync_project_note=AsyncMock(),_fast_path_answer=lambda _:None,
            memory_queue=types.SimpleNamespace(enqueue=AsyncMock()),
            # Post-reply knowledge extraction (knowledge.py). Fire-and-forget
            # and synchronous to call, so a plain Mock is the right stub --
            # chat() must not await it.
            knowledge=types.SimpleNamespace(learn_in_background=Mock()),
            notify=types.SimpleNamespace(notify=AsyncMock()),
            # Deterministic desktop commands ("close Discord") that skip the
            # model entirely. match() returning None is the ordinary-message
            # path, which is what this test exercises; nova_tools is only
            # reached once a command has matched.
            desktop_intents=types.SimpleNamespace(match=lambda _m: None),
            # Coursework lookups answered from rows. None is the
            # ordinary-message path this test exercises.
            school_intents=types.SimpleNamespace(match=lambda _m: None, answer=AsyncMock()),
            nova_tools=types.SimpleNamespace(
                autonomy_level=AsyncMock(return_value="full"),
                needs_approval=lambda *a: False,
                refused_by_autonomy=lambda *a: False,
                execute=AsyncMock(return_value={"ok": True, "result": []}),
            ),
            _describe_windows=lambda _r: "",
            _unsaved_window_blocking=AsyncMock(return_value=None),
            _category_for=AsyncMock(return_value="research"),
            re=__import__("re"),
            # chat() no longer routes through the director -- it streams from
            # agent_loop, which runs tools inline. These are the globals that
            # arrived with that change; the assertion below is what forces this
            # list to be kept honest rather than guessed at.
            agent_loop=types.SimpleNamespace(run=_fake_agent_loop_run),
            # expand returns (text, flags) or None; direct returns a string or
            # None. An ordinary (non-slash) message takes the None path in both.
            commands=types.SimpleNamespace(direct=lambda _m: None, expand=lambda _m: None),
            operator_tools=types.SimpleNamespace(capability_answer=lambda _m: None),
            base64=__import__("base64"),dev_server=types.SimpleNamespace(),ide=types.SimpleNamespace(),
            NOVA_AGENCY_INSTRUCTIONS="",HOMEWORK_SOLVE_INSTRUCTIONS="",
            get_nova_persona_instructions=lambda *a: "Nova test persona",
            _build_environment_context=AsyncMock(return_value=""),
            asyncio=asyncio,app=types.SimpleNamespace(),HTTPException=type("HTTPException",(Exception,),{}),
            providers=package.providers,routing=package.routing,code_files=package.code_files,
            project_context=types.SimpleNamespace(context_for=lambda *a,**k:None,wants_project_context=lambda *a,**k:False),
            image_gen=types.SimpleNamespace(detect_image_request=lambda _:None, is_available=lambda: False),
            HOMEWORK_MODE_INSTRUCTIONS="",_format_attachment_for_model=lambda *a,**k:"",
            # Real module, not a stub: chat() asks it whether this turn has
            # images and whether the routed model can see them, and both
            # answers steer the request. A stub returning falsy for everything
            # would make this test pass while exercising a path no image ever
            # takes.
            vision=vision,
            _maybe_run_handoff_review=_no_handoff,_granted_roots=AsyncMock(return_value=[]),
            # Real module: the send/stop bookkeeping is stdlib-only.
            chat_runs=load("chat_runs"))
        package.routing.is_homework=lambda *a, **kw: False
        package.db.get_user_profile=AsyncMock(return_value={"name": "Student"})
        package.providers.ProviderUnavailableError=type("ProviderUnavailable",(Exception,),{})
        package.providers.message_mentions_files=lambda *a,**k:False
        async def _no_file_tools(*a,**k):
            yield {"type":"_final_messages","messages":a[2] if len(a)>2 else []}
        package.providers.run_file_tool_loop=_no_file_tools
        # Fail loudly and specifically if chat() grows a dependency this env
        # does not provide. Without this, a missing name surfaces as whatever
        # AttributeError the exception machinery hits on the way out -- which
        # is how a previous drift showed up as a confusing complaint about
        # providers.ProviderUnavailableError rather than the real cause.
        assigned={n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
        assigned|={a.arg for a in ast.walk(node) if isinstance(a,ast.arg)}
        assigned|={h.name for h in ast.walk(node) if isinstance(h,ast.ExceptHandler) and h.name}
        assigned|={f.name for f in ast.walk(node) if isinstance(f,(ast.FunctionDef,ast.AsyncFunctionDef)) and f is not node}
        read={n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
        missing=sorted(read-assigned-set(env)-set(dir(__builtins__ if isinstance(__builtins__,dict) else __builtins__))-set(dir(__import__("builtins"))))
        self.assertEqual(missing,[],f"chat() reads globals this test env does not stub: {missing}")
        # Names alone are not enough. `providers` being stubbed says nothing
        # about `providers.message_mentions_files` existing on it, and a missing
        # ATTRIBUTE raises inside chat()'s broad `except`, which silently
        # reroutes the flow and fails an unrelated assertion further down -- that
        # has now happened three times while extending this file. Asserting every
        # attribute is stubbed is too strict (chat() has branches this test never
        # takes), so instead fill the gaps: any attribute chat() reads off a
        # stubbed module that does not exist gets an AsyncMock, or a real
        # exception class when the name is used in an `except`. The flow then
        # cannot change just because a new dependency appeared.
        handled={h.type.attr for h in ast.walk(node)
                 if isinstance(h,ast.ExceptHandler) and isinstance(h.type,ast.Attribute)}
        for n in ast.walk(node):
            if not (isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and isinstance(n.ctx,ast.Load)):
                continue
            target=env.get(n.value.id)
            if not isinstance(target,types.ModuleType) or hasattr(target,n.attr):
                continue
            filler=type(n.attr,(Exception,),{}) if n.attr in handled else AsyncMock()
            setattr(target,n.attr,filler)
        exec(compile(ast.Module(body=[node],type_ignores=[]),"main.py","exec"),env)
        request=types.SimpleNamespace(conversation_id=1,message="Research and review this",attachment_ids=[],homework=False,override_model_id=None)
        response=await env["chat"](request);events=[e async for e in response]
        # The guarantee worth protecting: the reply is written to the
        # conversation exactly once. Streaming and persisting are separate steps,
        # and persisting inside the stream loop (or in both places) is the easy
        # mistake -- it shows up as the same answer appearing twice in history.
        self.assertEqual(len([m for m in self.messages if m["role"]=="assistant"]),1,
                         "the assistant reply must be persisted exactly once")
        text="".join(e.get("content","") for e in events if e.get("type")=="token")
        self.assertIn("streamed answer",text,"tokens from agent_loop should reach the client")
        self.assertEqual(events[-1]["type"],"done","the stream must terminate with a done event")
    async def test_local_requests_serialize(self):
        active=0;peak=0
        async def complete(**kw):
            nonlocal active,peak
            active+=1;peak=max(peak,active);await asyncio.sleep(.02);active-=1;return "ok"
        with patch.object(llm,"acompletion",complete):await asyncio.gather(*(local.completion(model="ollama_chat/test") for _ in range(4)))
        self.assertEqual(peak,1)
    async def test_stream_holds_slot_until_closed(self):
        async def source():yield "first";yield "second"
        async def complete(**kw):return source() if kw.get("stream") else "ok"
        with patch.object(llm,"acompletion",complete):
            stream=await local.completion(model="ollama_chat/test",stream=True);self.assertEqual(await anext(stream),"first")
            waiting=asyncio.create_task(local.completion(model="ollama_chat/test"));await asyncio.sleep(.02);self.assertFalse(waiting.done())
            await stream.aclose();self.assertEqual(await asyncio.wait_for(waiting,1),"ok")
    async def test_cancelled_waiter_does_not_steal_slot(self):
        await local._slot.acquire();waiting=asyncio.create_task(local.completion(model="ollama_chat/test"))
        await asyncio.sleep(0);waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiting
        self.assertTrue(local._slot.locked());local._slot.release()

    async def test_close_stream_before_first_chunk(self):
        async def source():yield "first"
        with patch.object(llm,"acompletion",AsyncMock(return_value=source())):
            stream=await local.completion(model="ollama_chat/test",stream=True)
            await stream.aclose()
            self.assertFalse(local._slot.locked())

    async def test_local_request_failure_releases_slot(self):
        with patch.object(llm,"acompletion",AsyncMock(side_effect=RuntimeError("offline"))):
            with self.assertRaises(RuntimeError):await local.completion(model="ollama_chat/test")
        self.assertFalse(local._slot.locked())

if __name__=="__main__":unittest.main()
