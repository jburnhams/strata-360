import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, withBase, type AgentImage, type AgentPending, type AgentStatus, type AgentStep, type AgentTurn, type AgentUndoState } from '../api'
import { PanelSkeleton } from './Skeleton'

// Ask questions about the project in plain words: a hosted model answers by looking things up with read-only tools (the clips, the transcript, the edit plan, the script ...). It cannot change anything.
// What the tools return while answering goes to the model service (never pictures); the key stays on the server.
type Msg = AgentTurn & { steps?: AgentStep[]; images?: AgentImage[]; error?: boolean }

const EXAMPLES = ['How many clips are there, and which is the longest?', 'Does anyone mention the weather? Quote it and say where.', 'What is the film plan doing in its first minute?', 'Which transcript phrases are most likely wrong?', 'Show me a frame from the longest clip, looking behind the runner.']

/** `text` with **bold**, `code` and the ids of known clips turned into elements (a clip id is a button that opens the clip). */
export function inline(text: string, ids: string[], open: (clip: string) => void): ReactNode[] {
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(\\*\\*[^*]+\\*\\*|\`[^\`]+\`${ids.length ? '|' + [...ids].sort((a, b) => b.length - a.length).map(esc).join('|') : ''})`, 'g')
  return text.split(re).map((part, i) => {
    if (!part) return null
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <b key={i}>{inline(part.slice(2, -2), ids, open)}</b>
    const bare = part.startsWith('`') && part.endsWith('`') && part.length > 2 ? part.slice(1, -1) : part
    if (ids.includes(bare)) return <button key={i} onClick={() => open(bare)} title="open this clip" className="font-mono text-emerald-700 underline dark:text-emerald-400">{bare}</button>
    if (bare !== part) return <code key={i} className="rounded bg-stone-100 px-1 text-[0.9em] dark:bg-stone-800">{bare}</code>
    return part
  })
}

function Steps({ steps }: { steps: AgentStep[] }) {
  if (!steps.length) return null
  return (
    <details className="mt-1 text-xs text-stone-500">
      <summary className="cursor-pointer">Looked at {steps.length} {steps.length === 1 ? 'thing' : 'things'}: {[...new Set(steps.map(s => s.tool))].join(', ')}</summary>
      <ul className="mt-1 space-y-0.5 font-mono">
        {steps.map((s, i) => <li key={i} className={s.error ? 'text-red-600 dark:text-red-400' : ''}>{s.tool}({Object.entries(s.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')}) · {s.seconds} s{s.error ? ` · ${s.error}` : ''}</li>)}
      </ul>
    </details>
  )
}

export default function AskPage({ folder, clipIds, onOpenClip }: { folder: string; clipIds: string[]; onOpenClip: (clip: string) => void }) {
  const [status, setStatus] = useState<AgentStatus | null | undefined>(undefined)       // undefined: asking, null: the server could not say
  const [msgs, setMsgs] = useState<Msg[]>([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [vision, setVision] = useState(false); const [write, setWrite] = useState(false); const [pending, setPending] = useState<AgentPending[]>([]); const [deciding, setDeciding] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null); const gen = useRef(0)
  useEffect(() => { let live = true; api.agent().then(s => live && setStatus(s)).catch(() => live && setStatus(null)); return () => { live = false } }, [])
  const [undo, setUndo] = useState<AgentUndoState | null>(null); const [undoing, setUndoing] = useState(false)
  const refresh = (live: () => boolean = () => true) => {                                                         // what waits for approval (an outside agent may have asked) and what an undo would do
    api.agentPending(folder).then(r => live() && setPending(r.pending)).catch(() => {}); api.agentJournal(folder).then(r => live() && setUndo(r.undo)).catch(() => {})
  }
  useEffect(() => {                                                                                                // another project: a new conversation; what waits there is shown, and kept fresh while the page is open
    gen.current++; setMsgs([]); setBusy(false); setPending([]); setUndo(null); let on = true; const live = () => on
    refresh(live); const t = window.setInterval(() => refresh(live), 5000); return () => { on = false; window.clearInterval(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder])
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [msgs, busy])
  if (status === undefined) return <PanelSkeleton title="Ask about the project" rows={4} />

  const send = async (question: string) => {
    const q = question.trim(); if (!q || busy) return
    const history: Msg[] = [...msgs.filter(m => !m.error), { role: 'user', content: q }]; const mine = gen.current
    setMsgs([...msgs, { role: 'user', content: q }]); setText(''); setBusy(true)
    try {
      const r = await api.ask(folder, history.map(({ role, content }) => ({ role, content })), vision, write)
      if (mine === gen.current) { setMsgs(m => [...m, { role: 'assistant', content: r.answer, steps: r.steps, images: r.images }]); if (r.pending) setPending(r.pending); refresh(() => mine === gen.current) }
    } catch (e) {
      if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: e instanceof Error ? e.message : 'The assistant did not answer.', error: true }])
    } finally { if (mine === gen.current) setBusy(false) }
  }
  const decide = async (p: AgentPending, approve: boolean) => {
    setDeciding(p.id); const mine = gen.current
    try {
      const r = approve ? await api.agentApprove(folder, p.id) : null; if (!approve) await api.agentDeny(folder, p.id)
      if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: approve ? `Approved and done: ${r?.did ?? p.summary}.${r?.job ? ' It runs in the background.' : ''}` : `Denied: ${p.summary}.` }])
    } catch (e) { if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: e instanceof Error ? e.message : 'That did not work.', error: true }]) }
    finally { if (mine === gen.current) { setPending(ps => ps.filter(x => x.id !== p.id)); setDeciding(null); refresh(() => mine === gen.current) } }
  }
  const doUndo = async () => {
    setUndoing(true); const mine = gen.current
    try {
      const r = await api.agentUndo(folder)
      if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: `Undone: the project is back to before the assistant's last ${r.undone} change${r.undone === 1 ? '' : 's'} (${r.files} files restored). The state just before the undo is saved as ${r.checkpoint ?? 'the latest backup'}.` }])
    } catch (e) { if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: e instanceof Error ? e.message : 'The undo did not work.', error: true }]) }
    finally { if (mine === gen.current) { setUndoing(false); refresh(() => mine === gen.current) } }
  }
  const ready = status?.configured && status.available

  return (
    <section className="flex min-h-[60vh] flex-col rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-lg font-semibold">Ask about the project</h2>
        <span className="text-xs text-stone-500">{write ? 'edits allowed' : 'read only'} · {status?.model ?? 'no model'}</span></div>
      {!ready && <p role="status" className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
        {status === null ? 'The server did not say whether the assistant is set up.' : !status.available ? 'The assistant needs the mcp package on the server: pip install mcp.' : 'The assistant needs an NVIDIA_API_KEY: put NVIDIA_API_KEY=… in secrets.env next to the project and restart the server.'}</p>}
      <div role="log" aria-live="polite" aria-label="Conversation" className="min-h-0 flex-1 space-y-3 overflow-auto">
        {msgs.length === 0 && ready && <div className="text-sm text-stone-500"><p>It looks things up for each question, so ask about the footage, the transcript, the plan or the script. For example:</p>
          <ul className="mt-2 flex flex-wrap gap-2">{EXAMPLES.map(e => <li key={e}><button onClick={() => void send(e)} className="rounded-full border border-stone-300 px-3 py-1 text-xs hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800">{e}</button></li>)}</ul></div>}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : ''}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${m.role === 'user' ? 'bg-emerald-700 text-white' : m.error ? 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200' : 'bg-stone-100 dark:bg-stone-800'}`}>
              <div className="whitespace-pre-wrap break-words">{m.role === 'user' ? m.content : inline(m.content, clipIds, onOpenClip)}</div>
              {m.images && m.images.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{m.images.map(im => <figure key={im.url} className="max-w-xs"><a href={withBase(im.url)} target="_blank" rel="noreferrer" title="open the picture"><img src={withBase(im.url)} alt={im.caption} loading="lazy" className="w-full rounded-lg border border-stone-300 dark:border-stone-700" /></a><figcaption className="mt-0.5 text-xs text-stone-500">{im.caption}</figcaption></figure>)}</div>}
              {m.steps && <Steps steps={m.steps} />}
            </div>
          </div>))}
        {busy && <p className="text-sm text-stone-500" role="status">Looking…</p>}
        <div ref={end} />
      </div>
      {undo?.available && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-stone-100 p-2 text-sm dark:bg-stone-800">
        <span>The assistant made {undo.changes} change{undo.changes === 1 ? '' : 's'}{undo.since ? ` since ${new Date(undo.since * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}.</span>
        <button disabled={undoing} onClick={() => void doUndo()} title="Put the project back to how it was before the assistant's last changes. The current state is backed up first, and anything you changed since is undone too." className="rounded-lg border border-stone-400 px-3 py-1 disabled:opacity-40">Undo them</button></div>}
      {pending.length > 0 && <ul aria-label="Waiting for your approval" className="mt-3 space-y-2">
        {pending.map(p => <li key={p.id} className="rounded-lg border-2 border-amber-500 bg-amber-50 p-3 text-sm dark:bg-amber-950">
          <div><b>Needs your approval:</b> {p.summary}</div><div className="text-xs text-stone-600 dark:text-stone-400">Why: {p.why}.</div>
          <div className="mt-2 flex gap-2"><button disabled={deciding !== null} onClick={() => void decide(p, true)} className="rounded-lg bg-emerald-700 px-3 py-1 text-white disabled:opacity-40">Approve</button>
            <button disabled={deciding !== null} onClick={() => void decide(p, false)} className="rounded-lg border border-stone-400 px-3 py-1 disabled:opacity-40">Deny</button></div>
        </li>)}
      </ul>}
      <form className="mt-3 flex gap-2" onSubmit={e => { e.preventDefault(); void send(text) }}>
        <textarea aria-label="Your question" value={text} rows={2} disabled={!ready} onChange={e => setText(e.target.value)} placeholder={ready ? 'Ask a question…' : 'Not set up'}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(text) } }}
          className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-stone-50 p-2 text-sm disabled:opacity-50 dark:border-stone-700 dark:bg-stone-950" />
        <button type="submit" disabled={!ready || busy || !text.trim()} className="self-end rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Ask</button>
      </form>
      <label className="mt-2 flex items-center gap-2 text-xs text-stone-600 dark:text-stone-400" title="Off: the model never sees a picture, it is only shown to you. On: each picture is sent to a vision model that describes it in words."><input type="checkbox" checked={vision} disabled={!ready} onChange={e => setVision(e.target.checked)} /> Let the model see the pictures it fetches (sent to {status?.vision_model ?? 'a vision model'})</label>
      <label className="mt-1 flex items-center gap-2 text-xs text-stone-600 dark:text-stone-400" title="Off: the assistant can only look. On: it can change the plan, transcript, notes and script like you can; every change is backed up and journalled, and costly or heavy actions wait for your approval here."><input type="checkbox" checked={write} disabled={!ready} onChange={e => setWrite(e.target.checked)} /> Allow edits (backed up and journalled; costly or heavy actions still wait for your approval)</label>
      <p className="mt-2 text-xs text-stone-500">Your question and what the tools find (clip ids, transcript phrases, plan and script text) go to the model service. Pictures only do when the box above is ticked.</p>
    </section>
  )
}
