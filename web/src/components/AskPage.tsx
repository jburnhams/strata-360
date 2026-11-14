import { useEffect, useRef, useState } from 'react'
import { api, type AgentImage, type AgentPending, type AgentStatus, type AgentStep, type AgentTurn, type AgentUndoState } from '../api'
import { PanelSkeleton } from './Skeleton'
import { Button, Checkbox, Composer, Conversation, Tooltip, type ConversationTurn } from 'strata-react'

// Ask questions about the project in plain words: a hosted model answers by looking things up with read-only tools (the clips, the transcript, the edit plan, the script ...). It cannot change anything.
// What the tools return while answering goes to the model service (never pictures); the key stays on the server.
type Msg = AgentTurn & { id: string; at: number; steps?: AgentStep[]; images?: AgentImage[]; error?: boolean }
let seq = 0
const mk = (role: Msg['role'], content: string, o: Partial<Msg> = {}): Msg => ({ id: `m${++seq}`, at: Date.now(), role, content, ...o })

const EXAMPLES = ['How many clips are there, and which is the longest?', 'Does anyone mention the weather? Quote it and say where.', 'What is the film plan doing in its first minute?', 'Which transcript phrases are most likely wrong?', 'Show me a frame from the longest clip, looking behind the runner.']

function Steps({ steps, images }: { steps: AgentStep[]; images: AgentImage[] }) {
  return (
    <div className="type-caption text-muted-foreground">
      {steps.length > 0 && <ul className="space-y-0.5 font-mono">
        {steps.map((s, i) => <li key={i} className={s.error ? 'text-danger' : ''}>{s.tool}({Object.entries(s.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')}) · {s.seconds} s{s.error ? ` · ${s.error}` : ''}</li>)}
      </ul>}
      {images.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{images.map(im => <figure key={im.url} className="max-w-xs"><a href={im.url} target="_blank" rel="noreferrer"><img src={im.url} alt={im.caption} loading="lazy" className="w-full rounded-surface border border-border" /></a><figcaption className="mt-0.5">{im.caption}</figcaption></figure>)}</div>}
    </div>
  )
}

export default function AskPage({ folder, clipIds, onOpenClip }: { folder: string; clipIds: string[]; onOpenClip: (clip: string) => void }) {
  const [status, setStatus] = useState<AgentStatus | null | undefined>(undefined)       // undefined: asking, null: the server could not say
  const [msgs, setMsgs] = useState<Msg[]>([]); const [busy, setBusy] = useState(false); const [vision, setVision] = useState(false); const [write, setWrite] = useState(false); const [pending, setPending] = useState<AgentPending[]>([]); const [deciding, setDeciding] = useState<string | null>(null)
  const gen = useRef(0)
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
  if (status === undefined) return <PanelSkeleton title="Ask about the project" rows={4} />

  const send = async (question: string, history0: Msg[] = msgs) => {
    const q = question.trim(); if (!q || busy) return
    const history: Msg[] = [...history0.filter(m => !m.error), mk('user', q)]; const mine = gen.current
    setMsgs([...history0, history[history.length - 1]]); setBusy(true)
    try {
      const r = await api.ask(folder, history.map(({ role, content }) => ({ role, content })), vision, write)
      if (mine === gen.current) { setMsgs(m => [...m, mk('assistant', r.answer, { steps: r.steps, images: r.images })]); if (r.pending) setPending(r.pending); refresh(() => mine === gen.current) }
    } catch (e) {
      if (mine === gen.current) setMsgs(m => [...m, mk('assistant', e instanceof Error ? e.message : 'The assistant did not answer.', { error: true })])
    } finally { if (mine === gen.current) setBusy(false) }
  }
  const stop = () => { gen.current++; setBusy(false) }                                                            // the answer on its way is dropped when it arrives
  const retry = (id: string) => {                                                                                  // ask the question before a failed answer again, in place of it
    const i = msgs.findIndex(m => m.id === id); const q = msgs[i - 1]; if (!q || q.role !== 'user') return
    void send(q.content, msgs.slice(0, i - 1))
  }
  const decide = async (p: AgentPending, approve: boolean) => {
    setDeciding(p.id); const mine = gen.current
    try {
      const r = approve ? await api.agentApprove(folder, p.id) : null; if (!approve) await api.agentDeny(folder, p.id)
      if (mine === gen.current) setMsgs(m => [...m, mk('assistant', approve ? `Approved and done: ${r?.did ?? p.summary}.${r?.job ? ' It runs in the background.' : ''}` : `Denied: ${p.summary}.`)])
    } catch (e) { if (mine === gen.current) setMsgs(m => [...m, mk('assistant', e instanceof Error ? e.message : 'That did not work.', { error: true })]) }
    finally { if (mine === gen.current) { setPending(ps => ps.filter(x => x.id !== p.id)); setDeciding(null); refresh(() => mine === gen.current) } }
  }
  const doUndo = async () => {
    setUndoing(true); const mine = gen.current
    try {
      const r = await api.agentUndo(folder)
      if (mine === gen.current) setMsgs(m => [...m, mk('assistant', `Undone: the project is back to before the assistant's last ${r.undone} change${r.undone === 1 ? '' : 's'} (${r.files} files restored). The state just before the undo is saved as ${r.checkpoint ?? 'the latest backup'}.`)])
    } catch (e) { if (mine === gen.current) setMsgs(m => [...m, mk('assistant', e instanceof Error ? e.message : 'The undo did not work.', { error: true })]) }
    finally { if (mine === gen.current) { setUndoing(false); refresh(() => mine === gen.current) } }
  }
  const ready = status?.configured && status.available
  const notReady = ready ? undefined : status === null ? 'The server did not say whether the assistant is set up.' : !status.available ? 'The assistant needs the mcp package on the server: pip install mcp.' : 'The assistant needs an NVIDIA_API_KEY: put NVIDIA_API_KEY=… in secrets.env next to the project and restart the server.'
  const turns: ConversationTurn[] = msgs.map(m => m.role === 'user' ? { id: m.id, role: 'person', time: m.at, text: m.content }
    : m.error ? { id: m.id, role: 'answer', time: m.at, text: '', state: 'failed', error: m.content }
    : { id: m.id, role: 'answer', time: m.at, text: m.content, lookedUp: m.steps?.length || m.images?.length ? <Steps steps={m.steps ?? []} images={m.images ?? []} /> : undefined })
  if (busy) turns.push({ id: 'answering', role: 'answer', time: Date.now(), text: '', state: 'streaming' })

  return (
    <section className="flex min-h-[60vh] flex-col rounded-overlay border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h2 className="type-heading font-semibold">Ask about the project</h2>
        <span className="type-caption text-muted-foreground">{write ? 'edits allowed' : 'read only'} · {status?.model ?? 'no model'}</span></div>
      <Conversation label="Conversation" className="min-h-0 flex-1" turns={turns} answerName="Assistant" personName="You" entities={clipIds} onOpen={onOpenClip} onRetry={retry} lookedUpLabel="What it looked at"
        empty={<p className="type-body-sm text-muted-foreground">It looks things up for each question, so ask about the footage, the transcript, the plan or the script.</p>} />
      {undo?.available && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-surface bg-muted p-2 type-body-sm">
        <span>The assistant made {undo.changes} change{undo.changes === 1 ? '' : 's'}{undo.since ? ` since ${new Date(undo.since * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}.</span>
        <Tooltip label="Put the project back to how it was before the assistant's last changes. The current state is backed up first, and anything you changed since is undone too."><Button disabled={undoing} onClick={() => void doUndo()}>Undo them</Button></Tooltip></div>}
      {pending.length > 0 && <ul aria-label="Waiting for your approval" className="mt-3 space-y-2">
        {pending.map(p => <li key={p.id} className="rounded-surface border-2 border-warning bg-warning-subtle p-3 type-body-sm">
          <div><b>Needs your approval:</b> {p.summary}</div><div className="type-caption text-muted-foreground">Why: {p.why}.</div>
          <div className="mt-2 flex gap-2"><Button variant="default" disabled={deciding !== null} onClick={() => void decide(p, true)}>Approve</Button>
            <Button disabled={deciding !== null} onClick={() => void decide(p, false)}>Deny</Button></div>
        </li>)}
      </ul>}
      <Composer label="Your question" onSend={q => void send(q)} answering={busy} onStop={stop} answeringReason="Looking…" suggestions={ready ? EXAMPLES : undefined} sendLabel="Ask" disabled={notReady} className="mt-3" />
      <Checkbox label={`Let the model see the pictures it fetches (sent to ${status?.vision_model ?? 'a vision model'})`} checked={vision} onCheckedChange={(checked: boolean) => setVision(checked)} disabled={!ready} title="Off: the model never sees a picture, it is only shown to you. On: each picture is sent to a vision model that describes it in words." />
      <Checkbox label="Allow edits (backed up and journalled; costly or heavy actions still wait for your approval)" checked={write} onCheckedChange={(checked: boolean) => setWrite(checked)} disabled={!ready} title="Off: the assistant can only look. On: it can change the plan, transcript, notes and script like you can; every change is backed up and journalled, and costly or heavy actions wait for your approval here." />
      <p className="mt-2 type-caption text-muted-foreground">Your question and what the tools find (clip ids, transcript phrases, plan and script text) go to the model service. Pictures only do when the box above is ticked.</p>
    </section>
  )
}
