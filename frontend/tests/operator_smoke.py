import asyncio, json, time, re, tempfile
from pathlib import Path
from playwright.async_api import async_playwright

HTML = '''<html><head><meta name="viewport" content="width=device-width, initial-scale=1" /></head><body style="background:#101216;color:white;margin:16px"><div id="root"></div>
<script type="module">
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>(type)=>type;window.__vite_plugin_react_preamble_installed__=true;
</script><script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import OperatorPanel from '/src/components/school/OperatorPanel.jsx';
import '/src/index.css';
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(OperatorPanel));
</script></body></html>'''

async def main():
    state = {'stopped':False,'tasks':[],'drafts':[{'id':'fixture','title':'Research essay','status':'prepared','url':'https://school.example/courses/12/assignments/34','text':'Reviewable draft — citations and conclusions.','files':[],'sources':['https://example.org/reference'],'notes':'Ready for review.'}],'grants':[],'budgets':[{'id':'b','title':'Weekend project','budget_cents':10000,'expenses_cents':1200,'income_cents':2500,'reservations':{'r':{'status':'unknown','amount_cents':500}}}]}
    calls=[]; errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.route(re.compile(r'http://127\.0\.0\.1:5177/operator-fixture\.html.*'),lambda route:route.fulfill(body=HTML,content_type='text/html'))
        async def api(route):
            req=route.request
            if req.method=='OPTIONS':
                await route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'});return
            assert req.headers.get('authorization')=='Bearer fixture-token', req.headers
            calls.append(req.url)
            if req.url.endswith('/stop'): state['stopped']=True
            if req.url.endswith('/resume'): state['stopped']=False
            if req.url.endswith('/authorize'):
                body=req.post_data_json
                state['grants']=[{'url':body['url'],'enabled':body['enabled'],'expires_at':time.time()+86400}]
            if req.url.endswith('/submit'):
                state['drafts'][0].update(status='submitted',receipt={'submitted_at':'2026-09-23T16:00:00Z','attempt':1})
            await route.fulfill(json=state,headers={'Access-Control-Allow-Origin':'*'})
        await page.route('http://127.0.0.1:8000/**',api)
        await page.goto('http://127.0.0.1:5177/operator-fixture.html?token=fixture-token&backend=http://127.0.0.1:8000')
        await page.get_by_text('Operator · Ready',exact=False).wait_for()
        await page.locator('summary').first.click()
        await page.get_by_role('button',name='Stop operator').click()
        await page.get_by_text('Operator · Stopped',exact=False).wait_for()
        await page.get_by_role('button',name='Resume',exact=True).click()
        await page.get_by_text('Operator · Ready',exact=False).wait_for()
        submit=page.get_by_role('button',name='Submit authorized draft')
        assert await submit.is_disabled()
        await page.get_by_label('Canvas assignment URL').fill(state['drafts'][0]['url'])
        await page.get_by_role('button',name='Allow submission for 24 hours').click()
        await submit.wait_for()
        await page.get_by_text('Review draft',exact=True).click()
        await page.screenshot(path=str(Path(tempfile.gettempdir()) / 'nova-operator-phone.png'),full_page=True)
        await submit.click()
        await page.get_by_text('Canvas receipt:',exact=False).wait_for()
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Horizontal overflow'
        assert not errors, errors
        assert 'token=' not in page.url
        print(json.dumps({'mobile_controls':'passed','authenticated_requests':len(calls),'application_errors':errors}))
        await browser.close()

asyncio.run(main())
