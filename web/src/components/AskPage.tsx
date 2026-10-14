import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type AgentImage, type AgentStatus, type AgentStep, type AgentTurn } from '../api'
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
  const [msgs, setMsgs] = useState<Msg[]>([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [vision, setVision] = useState(false)
  const end = useRef<HTMLDivElement>(null); const gen = useRef(0)
  useEffect(() => { let live = true; api.agent().then(s => live && setStatus(s)).catch(() => live && setStatus(null)); return () => { live = false } }, [])
  useEffect(() => { gen.current++; setMsgs([]); setBusy(false) }, [folder])                                  // another project: a new conversation
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [msgs, busy])
  if (status === undefined) return <PanelSkeleton title="Ask about the project" rows={4} />

  const send = async (question: string) => {
    const q = question.trim(); if (!q || busy) return
    const history: Msg[] = [...msgs.filter(m => !m.error), { role: 'user', content: q }]; const mine = gen.current
    setMsgs([...msgs, { role: 'user', content: q }]); setText(''); setBusy(true)
    try {
      const r = await api.ask(folder, history.map(({ role, content }) => ({ role, content })), vision)
      if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: r.answer, steps: r.steps, images: r.images }])
    } catch (e) {
      if (mine === gen.current) setMsgs(m => [...m, { role: 'assistant', content: e instanceof Error ? e.message : 'The assistant did not answer.', error: true }])
    } finally { if (mine === gen.current) setBusy(false) }
  }
  const ready = status?.configured && status.available

  return (
    <section className="flex min-h-[60vh] flex-col rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-lg font-semibold">Ask about the project</h2>
        <span className="text-xs text-stone-500">read only · {status?.model ?? 'no model'}</span></div>
      {!ready && <p role="status" className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
        {status === null ? 'The server did not say whether the assistant is set up.' : !status.available ? 'The assistant needs the mcp package on the server: pip install mcp.' : 'The assistant needs an NVIDIA_API_KEY: put NVIDIA_API_KEY=… in secrets.env next to the project and restart the server.'}</p>}
      <div role="log" aria-live="polite" aria-label="Conversation" className="min-h-0 flex-1 space-y-3 overflow-auto">
        {msgs.length === 0 && ready && <div className="text-sm text-stone-500"><p>It looks things up for each question, so ask about the footage, the transcript, the plan or the script. For example:</p>
          <ul className="mt-2 flex flex-wrap gap-2">{EXAMPLES.map(e => <li key={e}><button onClick={() => void send(e)} className="rounded-full border border-stone-300 px-3 py-1 text-xs hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800">{e}</button></li>)}</ul></div>}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : ''}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${m.role === 'user' ? 'bg-emerald-700 text-white' : m.error ? 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200' : 'bg-stone-100 dark:bg-stone-800'}`}>
              <div className="whitespace-pre-wrap break-words">{m.role === 'user' ? m.content : inline(m.content, clipIds, onOpenClip)}</div>
              {m.images && m.images.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{m.images.map(im => <figure key={im.url} className="max-w-xs"><a href={im.url} target="_blank" rel="noreferrer" title="open the picture"><img src={im.url} alt={im.caption} loading="lazy" className="w-full rounded-lg border border-stone-300 dark:border-stone-700" /></a><figcaption className="mt-0.5 text-xs text-stone-500">{im.caption}</figcaption></figure>)}</div>}
              {m.steps && <Steps steps={m.steps} />}
            </div>
          </div>))}
        {busy && <p className="text-sm text-stone-500" role="status">Looking…</p>}
        <div ref={end} />
      </div>
      <form className="mt-3 flex gap-2" onSubmit={e => { e.preventDefault(); void send(text) }}>
        <textarea aria-label="Your question" value={text} rows={2} disabled={!ready} onChange={e => setText(e.target.value)} placeholder={ready ? 'Ask a question…' : 'Not set up'}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(text) } }}
          className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-stone-50 p-2 text-sm disabled:opacity-50 dark:border-stone-700 dark:bg-stone-950" />
        <button type="submit" disabled={!ready || busy || !text.trim()} className="self-end rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Ask</button>
      </form>
      <label className="mt-2 flex items-center gap-2 text-xs text-stone-600 dark:text-stone-400" title="Off: the model never sees a picture, it is only shown to you. On: each picture is sent to a vision model that describes it in words."><input type="checkbox" checked={vision} disabled={!ready} onChange={e => setVision(e.target.checked)} /> Let the model see the pictures it fetches (sent to {status?.vision_model ?? 'a vision model'})</label>
      <p className="mt-2 text-xs text-stone-500">Your question and what the tools find (clip ids, transcript phrases, plan and script text) go to the model service. Pictures only do when the box above is ticked.</p>
    </section>
  )
}
