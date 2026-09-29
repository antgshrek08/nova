import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '../../api.js';

async function request(path, body) {
  const response = await fetch(`${BACKEND_URL}/operator${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The operator request failed.');
  return data;
}

const button = 'min-h-11 rounded border border-charcoal-600 px-3 py-2 text-xs hover:bg-charcoal-700 disabled:opacity-40';

function Evidence({ path, label }) {
  const [image, setImage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => () => { if (image) URL.revokeObjectURL(image); }, [image]);
  async function show() {
    try {
      const response = await fetch(`${BACKEND_URL}/operator${path}`);
      if (!response.ok) throw new Error('This screenshot is unavailable.');
      setImage(URL.createObjectURL(await response.blob()));
    } catch (e) { setError(e.message); }
  }
  return <div className="mt-2"><button className={button} onClick={show}>{label}</button>{error && <p role="alert">{error}</p>}{image && <img className="mt-2 w-full rounded" src={image} alt={label} />}</div>;
}

export default function OperatorPanel({ assignments = [] }) {
  const [state, setState] = useState(null);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [packet, setPacket] = useState(null);
  const [connection, setConnection] = useState(null);
  const [browserAssignments, setBrowserAssignments] = useState([]);
  const refresh = useCallback(async () => {
    try { setState(await request('/status')); } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 10000); return () => clearInterval(timer); }, [refresh]);
  async function act(fn) {
    setBusy(true); setError('');
    try { await fn(); await refresh(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const grants = (state?.grants || []).filter(g => g.enabled && g.expires_at * 1000 > Date.now());
  return <details className="mb-5 rounded-lg border border-charcoal-700 bg-charcoal-900/50 p-4">
    <summary className="cursor-pointer text-sm font-medium text-charcoal-100">Operator · {!state ? 'Connecting' : state.stopped ? 'Stopped' : 'Ready'} · {state?.drafts?.length || 0} {state?.drafts?.length === 1 ? 'draft' : 'drafts'}</summary>
    <div className="mt-4 space-y-4 text-sm text-charcoal-300">
      <p>Ask Nova in chat to work on an assignment. It saves a draft here. Authorize a specific assignment if you want Nova to submit it automatically after preparing the work.</p>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy} onClick={() => act(async () => setConnection(await request('/canvas/connect', {url})))}>Open Canvas / check sign-in</button>
        <button className={button} disabled={busy} onClick={() => act(async () => { const result = await request('/canvas/assignments', {url}); setBrowserAssignments(result.assignments); if (result.truncated) setError('Canvas returned a partial list. Ask Nova to inspect the remaining courses.'); })}>Find current assignments</button>
      </div>
      {connection && <p className="text-xs">{connection.message}{connection.name && ` Signed in as ${connection.name}.`}</p>}
      <div className="flex flex-wrap gap-2">
        <button className={button} onClick={() => act(() => request('/stop', {}))}>Stop operator</button>
        <button className={button} disabled={busy || !state?.stopped} onClick={() => act(() => request('/resume', {}))}>Resume</button>
        <button className={button} disabled={busy} onClick={refresh}>Refresh</button>
      </div>
      {error && <p role="alert" className="text-rose-300">{error}</p>}
      <label className="block text-xs">Assignment
        <select aria-label="Choose assignment" className="mt-1 min-h-11 w-full rounded bg-charcoal-800 p-2 text-base sm:text-sm" value={url} onChange={e => { setUrl(e.target.value); setPacket(null); }}>
          <option value="">Choose an assignment</option>
          {(browserAssignments.length ? browserAssignments : assignments).filter(a => a.url).map(a => <option key={a.url} value={a.url}>{a.course_name} · {a.display_title || a.title}</option>)}
        </select>
      </label>
      <input aria-label="Canvas assignment URL" placeholder="Or paste the Canvas assignment URL" className="min-h-11 w-full rounded bg-charcoal-800 p-2 text-base sm:text-xs" value={url} onChange={e => { setUrl(e.target.value); setPacket(null); }} />
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy || !url} onClick={() => act(async () => setPacket(await request('/assignment', { url })))}>Read instructions</button>
        <button className={button} disabled={busy || !url} onClick={() => act(() => request('/authorize', { url, enabled: true, hours: 24 }))}>Allow submission for 24 hours</button>
      </div>
      {packet && <div className="rounded bg-charcoal-800 p-3"><strong>{packet.title}</strong><p className="mt-2 whitespace-pre-wrap text-xs">{packet.instructions}</p><p className="mt-2 text-xs">Accepted: {packet.submission_types.join(', ')}{packet.locked ? ' · Locked' : ''}</p></div>}
      {grants.map(g => <div key={g.url} className="flex items-center justify-between gap-3 text-xs"><span className="break-all">Authorized: {g.url}<br/>Until {new Date(g.expires_at * 1000).toLocaleString()}</span><button className={button} disabled={busy} onClick={() => act(() => request('/authorize', { url: g.url, enabled: false }))}>Revoke</button></div>)}
      {(state?.topics || []).map(topic => <article key={topic.id} className="rounded border border-charcoal-700 p-3"><strong>Essay topic: {topic.topic}</strong><p className="my-2 text-xs">{topic.rationale}</p><button className={button} disabled={busy || topic.approved} onClick={() => act(() => request('/topics/approve', {topic_id:topic.id}))}>{topic.approved ? 'Topic approved' : 'Approve this topic'}</button></article>)}
      {(state?.drafts || []).map(draft => <article key={draft.id} className="rounded border border-charcoal-700 p-3">
        <div className="font-medium">{draft.title} <span className="text-xs text-charcoal-400">· {draft.status}</span></div>
        <details className="my-2 text-xs"><summary className="cursor-pointer">Review draft</summary><p className="mt-2 whitespace-pre-wrap">{draft.text || draft.submission_url}</p>{draft.files.map(f => <p key={f.path}>{f.name} · {f.size} bytes</p>)}<p>{draft.notes}</p>{draft.sources.map(s => <p className="break-all" key={s}>{s}</p>)}</details>
        {draft.receipt?.submitted_at && <p className="text-xs text-emerald-300">Canvas receipt: {draft.receipt.submitted_at} · attempt {draft.receipt.attempt}</p>}
        {draft.error && <p className="text-xs text-amber-300">{draft.error}</p>}
        {draft.started_at && <Evidence path={`/drafts/${draft.id}/evidence/prepared`} label="Prepared form screenshot" />}
        {draft.receipt?.submitted_at && <Evidence path={`/drafts/${draft.id}/evidence/receipt`} label="Receipt screenshot" />}
        <div className="mt-2 flex flex-wrap gap-2">
          {draft.review_required && !draft.essay_reviewed && <button className={button} disabled={busy} onClick={() => act(() => request(`/drafts/${draft.id}/approve`, {}))}>Approve written draft</button>}
          <button className={button} disabled={busy || draft.status !== 'prepared' || (draft.review_required && !draft.essay_reviewed) || !grants.some(g => g.url === draft.url && (!g.user_id || g.user_id === draft.packet?.user_id))} onClick={() => act(() => request(`/drafts/${draft.id}/submit`, {}))}>Submit authorized draft</button>
          <button className={button} disabled={busy} onClick={() => act(() => request(`/drafts/${draft.id}/reconcile`, {}))}>Check receipt</button>
        </div>
      </article>)}
      {(state?.tasks || []).slice(0, 5).map(t => <div key={t.id} className="text-xs"><strong>{t.workflow}</strong> · {t.status}{t.seconds != null && ` · ${t.seconds}s`}<p>{t.summary}</p>{t.steps?.length > 0 && <p>{t.steps.at(-1).evidence || t.steps.at(-1).error || 'Awaiting evidence'}</p>}</div>)}
      {(state?.tasks || []).slice(0, 5).filter(t => t.steps?.at(-1)?.evidence_id).map(t => <details key={t.id}><summary className="cursor-pointer text-xs">{t.workflow} screenshots</summary>{['before', 'after'].map(kind => <Evidence key={kind} path={`/tasks/${t.id}/evidence/${t.steps.at(-1).evidence_id}/${kind}`} label={`${kind === 'before' ? 'Before' : 'After'} the last action`} />)}</details>)}
      {(state?.budgets || []).map(b => <p key={b.id} className="text-xs">{b.title}: spent ${(b.expenses_cents / 100).toFixed(2)} of ${(b.budget_cents / 100).toFixed(2)} · pending ${(Object.values(b.reservations || {}).filter(r => ['reserved', 'executing', 'unknown'].includes(r.status)).reduce((sum, r) => sum + r.amount_cents, 0) / 100).toFixed(2)} · income ${(b.income_cents / 100).toFixed(2)} · net ${((b.income_cents - b.expenses_cents) / 100).toFixed(2)}</p>)}
    </div>
  </details>;
}
