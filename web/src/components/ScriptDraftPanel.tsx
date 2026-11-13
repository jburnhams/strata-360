import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type ScriptItem, type ScriptPins, type Seg, type VoPin } from '../api'
import { usePoll } from '../usePoll'
import { usedSet } from '../marks'
import { diffDrafts } from '../scriptDiff'
import { addNever, addPin, editNarration, highlight, removeNever, removePin, setMode } from '../scriptPins'
import { PanelSkeleton } from './Skeleton'
import Phrase from './Phrase'
import WordMarker from './WordMarker'
import RoughMixPlayer from './RoughMixPlayer'
import { Button, Checkbox, Input, NativeSelect, Textarea, Tooltip } from 'strata-react'

const KIND: Record<ScriptItem['type'], { label: string; cls: string }> = {
  vo: { label: 'narration', cls: 'bg-info-subtle text-info' },
  clip: { label: 'you', cls: 'bg-primary-3 text-primary' },
  gap: { label: 'gap', cls: 'bg-warning-subtle text-warning' },
  sing: { label: 'sung', cls: 'bg-info-subtle text-info' },
  broll: { label: 'b-roll', cls: 'bg-muted text-foreground' },
}
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
const itemOf = (msg: string) => { const m = msg.match(/^item (\d+):/); return m ? Number(m[1]) : null }

// The whole-race script, as written by the script writer from everything it knows: your own lines (words coloured as in the transcript: select words to mark them), narration, and b-roll, in film order.
// "Revise" sends the draft back with your marks and pins and gets a new draft that keeps everything they do not touch; items new since the previous draft are flagged.
/** An item's basis as a list: older drafts (and some model output) have one string. */
function basisOf(it: { basis?: unknown }): string[] { return Array.isArray(it.basis) ? it.basis.map(String) : typeof it.basis === 'string' && it.basis.trim() ? [it.basis] : [] }

export default function ScriptDraftPanel({ folder }: { folder: string }) {
  const [ver, setVer] = useState(0)
  const st = usePoll(() => api.script2(folder), 4000, [folder, ver])
  const tr = usePoll(() => api.transcript(folder), 30000, [folder, ver])
  const [prevName, setPrevName] = useState<string | null>(null)
  const [prevItems, setPrevItems] = useState<ScriptItem[]>()
  const [target, setTarget] = useState(''), [auto, setAuto] = useState(false), [err, setErr] = useState<string>(), [busy, setBusy] = useState(false)
  const draft = st?.draft ?? null
  const pins: ScriptPins = st?.pins ?? {}
  const [edited, setEdited] = useState<Record<number, string>>({}), [editing, setEditing] = useState<number | null>(null), [text, setText] = useState('')
  const [vsel, setVsel] = useState<{ text: string; i: number; x: number; y: number }>()
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => { setEdited({}); setEditing(null) }, [draft?.created])
  useEffect(() => {
    const on = () => {
      const s = window.getSelection(), r = s && s.rangeCount ? s.getRangeAt(0) : null
      if (!r || r.collapsed || !list.current) { setVsel(undefined); return }
      const n = r.commonAncestorContainer, el = (n.nodeType === 1 ? (n as Element) : n.parentElement)?.closest<HTMLElement>('[data-vo]')
      const t = r.toString().trim()
      if (!el || !list.current.contains(el) || !t) { setVsel(undefined); return }
      const b = typeof r.getBoundingClientRect === 'function' ? r.getBoundingClientRect() : { left: 0, width: 0, top: 0 }
      setVsel({ text: t, i: Number(el.dataset.vo), x: b.left + b.width / 2, y: b.top })
    }
    document.addEventListener('selectionchange', on); return () => document.removeEventListener('selectionchange', on)
  }, [])
  useEffect(() => {
    const name = draft?.draft_of ?? null
    if (name === prevName) return
    setPrevName(name); setPrevItems(undefined)
    if (name) api.script2(folder, name).then(r => setPrevItems(r.draft?.items)).catch(() => {})
  }, [draft?.draft_of, folder, prevName])
  const segs = useMemo(() => { const m = new Map<string, Seg[]>(); for (const s of tr?.segments ?? []) { const k = `${s.clip}|${s.si}`; m.set(k, [...(m.get(k) ?? []), s]) } return m }, [tr])
  const used = useMemo(() => usedSet((draft?.items ?? []).flatMap(i => i.lines ?? [])), [draft])
  const diff = useMemo(() => diffDrafts(prevItems, draft?.items ?? []), [prevItems, draft])
  const warn = useMemo(() => { const m = new Map<number, string[]>(); for (const w of [...(draft?.problems ?? []), ...(draft?.warnings ?? [])]) { const n = itemOf(w); if (n) m.set(n, [...(m.get(n) ?? []), w.replace(/^item \d+: /, '')]) } return m }, [draft])
  if (!st) return <PanelSkeleton title="Film script" rows={5} />
  const go = async (revise: boolean) => {
    setBusy(true); setErr(undefined)
    try { const r = await api.generateScript2(folder, { revise, target_s: target ? Number(target) : undefined, auto }); if (!r.started) setErr(r.reason ?? 'could not start'); setVer(v => v + 1) } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  const planIt = async () => { setBusy(true); setErr(undefined); try { const r = await api.planScript2(folder); if (!r.started) setErr(r.reason ?? 'could not start') ; setVer(v => v + 1) } catch (e) { setErr((e as Error).message) } setBusy(false) }
  const latest = st.drafts.length ? st.drafts[st.drafts.length - 1] : null
  const savePins = async (next: ScriptPins) => { try { await api.saveScriptPins(folder, next); setErr(undefined) } catch (e) { setErr((e as Error).message) } setVer(v => v + 1) }
  const pinVo = async (never: boolean) => {
    if (!vsel || !draft) return; const clip = draft.items[vsel.i]?.clip ?? ''
    window.getSelection()?.removeAllRanges(); setVsel(undefined); await savePins(never ? addNever(pins, vsel.text) : addPin(pins, vsel.text, clip))
  }
  const saveEdit = async (i: number, it: ScriptItem) => { const old = edited[i] ?? it.text ?? ''; setEditing(null); if (text.trim() === old.trim()) return; setEdited(e => ({ ...e, [i]: text.trim() })); await savePins(editNarration(pins, old, text.trim(), it.clip)) }
  const pinTexts = (clip: string) => (pins.vo ?? []).filter(p => p.mode !== 'clip' || p.clip === clip).map(p => p.text)
  const r = draft?.report
  const words = (it: ScriptItem) => (it.refs ?? []).map((ref, k) => {
    const ws = (segs.get(`${ref.clip}|${ref.si}`) ?? []).flatMap(s => s.words).filter((w, j) => { const i = w.i ?? j; return i >= ref.w0 && i < ref.w1 })
    return ws.length ? <span key={k} className="mr-1"><Phrase text="" en={null} lang="en" mode="translated" word={{ folder, clip: ref.clip, si: ref.si, words: ws, onSaved: () => setVer(v => v + 1), used }} /></span> : null
  })
  let lastClip = ''
  return (
    <section className="rounded-overlay border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="type-body-sm font-semibold">Film script</h3>
        <label className="type-caption text-muted-foreground">length (s) <Input type="number" min={30} value={target} onChange={e => setTarget(e.target.value)} placeholder="music / automatic" className="ml-1" /></label>
        <Checkbox label="ignore the music" checked={auto} onCheckedChange={(checked: boolean) => setAuto(checked)} />
        <Button variant="default" disabled={busy || st.running || !st.key_configured} onClick={() => go(!!draft)}>{st.running ? 'writing…' : draft ? 'Revise this draft' : 'Write a draft'}</Button>
        {draft && <Tooltip label="start again without the current draft"><Button disabled={busy || st.running || !st.key_configured} onClick={() => go(false)}>New draft</Button></Tooltip>}
      </div>
      {!st.key_configured && <p className="mt-2 type-body-sm text-warning">No Gemini API key is set: add it (secrets.env or the Script panel) to write a draft.</p>}
      {st.running && st.log.length > 0 && <p className="mt-2 font-mono type-caption text-muted-foreground">{st.log[st.log.length - 1]}</p>}
      {!st.running && st.last_exit != null && st.last_exit !== 0 && <p className="mt-2 type-body-sm text-danger">The last attempt failed: {st.log[st.log.length - 1] ?? `exit ${st.last_exit}`}</p>}
      {err && <p className="mt-2 type-body-sm text-danger">{err}</p>}
      {draft && (
        <div className="mt-2 flex flex-wrap items-center gap-3 type-body-sm">
          <Tooltip label="turn this draft into the film's plan: your lines, the narration (spoken and timed) and b-roll, cut on the beat"><Button disabled={busy || st.plan_running} onClick={() => void planIt()}>{st.plan_running ? 'planning…' : 'Make the film from this draft'}</Button></Tooltip>
          <span className="type-caption text-muted-foreground">{st.plan_running ? (st.plan_log?.[st.plan_log.length - 1] ?? 'speaking the narration and planning the windows…')
            : st.plan?.source === 'script' ? `Film plan: ${st.plan.windows} windows, ${st.plan.length_s} s, from ${st.plan.script === latest ? 'this draft' : 'an older draft (make the film again to use this one)'}`
            : 'The film plan is still the beat planner’s, not this script.'}</span>
        </div>)}
      {draft && !st.plan_running && <RoughMixPlayer folder={folder} version={ver} />}
      {!st.plan_running && st.plan_exit != null && st.plan_exit !== 0 && <p className="mt-1 type-body-sm text-danger">Planning failed: {st.plan_log?.[st.plan_log.length - 1] ?? `exit ${st.plan_exit}`}</p>}
      {st.plan?.source === 'script' && st.plan.warnings.length > 0 && <ul className="mt-1 list-disc pl-5 type-caption text-warning">{st.plan.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
      {!draft ? <p className="mt-2 type-body-sm text-muted-foreground">No draft yet. The writer reads every clip, your notes and the transcript, and writes a first script you can then mark up and revise.</p> : (<>
        <div className="mt-3">
          <div className="type-body font-medium">{draft.title ?? '(untitled)'}</div>
          {draft.story && <p className="type-body-sm italic text-muted-foreground">{draft.story}</p>}
          {draft.length_note && draft.length_note.verdict !== 'fits' && (
            <p role="note" data-length-note={draft.length_note.verdict} className="rounded-control border border-warning bg-warning-subtle p-2 type-body-sm text-warning">
              The writer says the {draft.length_note.verdict === 'too_long' ? 'length is too long' : 'length is too short'} for this material and music{draft.length_note.ideal_s ? `: about ${Math.floor(draft.length_note.ideal_s / 60)}:${String(Math.round(draft.length_note.ideal_s % 60)).padStart(2, '0')} would suit it better` : ''}. {draft.length_note.why}
            </p>
          )}
          {draft.length_note?.verdict === 'fits' && <p data-length-note="fits" className="type-caption text-muted-foreground">The writer thinks this length suits the material and the music.{draft.length_note.why ? ` ${draft.length_note.why}` : ''}</p>}
          <p className="mt-1 type-caption text-muted-foreground">{r?.total_s} s of {draft.target_s} s{draft.target_source ? ` (${draft.target_source})` : ''} · you {r?.clip_s} s · narration {r?.vo_s} s ({r?.vo_words} words at {draft.wpm} wpm) · b-roll {r?.broll_s} s · {r?.clips_used} clips used, {r?.clips_skipped} skipped · {draft.revised ? 'revised' : 'first draft'} {draft.created.replace('T', ' ')}{diff.added.size ? ` · ${diff.added.size} new, ${diff.removed.length} removed` : ''}</p>
        </div>
        <div ref={list}>
        <WordMarker folder={folder} onSaved={() => setVer(v => v + 1)}>
          <ol className="mt-3 space-y-1 type-body-sm">
            {draft.items.map((it, i) => {
              const head = it.clip !== lastClip; lastClip = it.clip; const w = warn.get(i + 1)
              return (
                <li key={i}>
                  {head && <div className="mt-2 font-mono type-caption text-muted-foreground">clip {it.clip}</div>}
                  <div className={`flex gap-2 rounded-control px-1 py-0.5 ${diff.added.has(i) ? 'bg-primary-3' : ''}`}>
                    <span className={`mt-0.5 h-fit shrink-0 rounded-pill px-2 type-caption ${KIND[it.type].cls}`}>{KIND[it.type].label}</span>
                    <span className="w-10 shrink-0 text-right font-mono type-caption text-muted-foreground">{it.seconds != null ? mmss(it.seconds) : ''}</span>
                    <span className="min-w-0 flex-1 leading-relaxed">
                      {it.type === 'vo' && (editing === i ? (
                        <span className="flex flex-col gap-1">
                          <Textarea aria-label={`Narration ${i + 1}`} value={text} onChange={e => setText(e.target.value)} rows={2} className="w-full" />
                          <span className="flex gap-1"><Button variant="default" size="sm" onClick={() => void saveEdit(i, it)}>save (pins this wording)</Button><Button size="sm" onClick={() => setEditing(null)}>cancel</Button></span>
                        </span>
                      ) : (<>
                        <span data-vo={i} title={basisOf(it).length ? 'based on: ' + basisOf(it).join(' · ') : undefined}>{highlight(edited[i] ?? it.text ?? '', pinTexts(it.clip), pins.vo_never ?? []).map((p, k) => <span key={k} className={p.kind === 'must' ? 'rounded-control bg-primary-3' : p.kind === 'never' ? 'rounded-control bg-danger-subtle' : ''}>{p.t}</span>)}</span>
                        <Tooltip label="edit the wording: your version is kept word for word in later drafts"><Button variant="ghost" size="sm" className="ml-1" aria-label={`Edit narration ${i + 1}`} onClick={() => { setText(edited[i] ?? it.text ?? ''); setEditing(i) }}>✎</Button></Tooltip>
                      </>))}
                      {it.type === 'clip' && (words(it).some(Boolean) ? words(it) : <span>{it.text}</span>)}
                      {it.type === 'broll' && <span className="text-muted-foreground">{it.why}</span>}
                      {it.type === 'gap' && <span className="text-muted-foreground">gap clip, {it.seconds} s: {it.why}</span>}
                      {it.type === 'sing' && <span className="text-muted-foreground">the track sings {it.phrase}{it.text ? `: “${it.text}”` : ''} ({it.seconds} s): {it.why}</span>}
                      {it.view && <span className="ml-2 type-caption text-muted-foreground">{it.view} view of you</span>}
                      {it.anchor && <span className="ml-2 type-caption text-muted-foreground" title={it.anchor.why}>anchored at {it.anchor.film_s} s</span>}
                      {diff.added.has(i) && <span className="ml-2 rounded-control bg-primary-3 px-1 type-caption text-primary">new</span>}
                      {w && <span className="ml-2 cursor-help text-warning" title={w.join('\n')} aria-label={`check: ${w.join('; ')}`}>⚠</span>}
                    </span>
                  </div>
                </li>)
            })}
          </ol>
        </WordMarker>
        {vsel && (
          <div role="toolbar" aria-label="Mark the selected narration" className="fixed z-50 flex items-center gap-1 rounded-surface border border-border bg-card p-1 shadow-overlay" style={{ left: Math.max(vsel.x - 120, 8), top: Math.max(vsel.y - 44, 8) }} onMouseDown={e => e.preventDefault()}>
            <Tooltip label="keep exactly these words, in this clip, in every later draft"><Button variant="ghost" size="sm" onClick={() => void pinVo(false)}>Say exactly this</Button></Tooltip>
            <Tooltip label="never say these words"><Button variant="ghost" size="sm" onClick={() => void pinVo(true)}>Never say</Button></Tooltip>
          </div>)}
        </div>
        {((pins.vo ?? []).length > 0 || (pins.vo_never ?? []).length > 0) && (
          <details className="mt-3 type-body-sm"><summary className="cursor-pointer type-caption text-muted-foreground">Your narration pins ({(pins.vo ?? []).length + (pins.vo_never ?? []).length})</summary>
            <ul className="mt-1 space-y-1">
              {(pins.vo ?? []).map((p: VoPin) => (
                <li key={p.id} className="flex flex-wrap items-center gap-2"><span className="rounded-control bg-primary-3 px-1 type-caption">say</span><span className="min-w-0 flex-1">{p.text}</span>
                  <NativeSelect size="sm" aria-label={`Where to say ${p.id}`} value={p.mode} onChange={e => void savePins(setMode(pins, p.id, e.target.value as VoPin['mode'], p.clip ?? draft.items.find(x => x.type === 'vo' && x.text?.includes(p.text))?.clip))}>
                    <option value="clip">in clip {p.clip ?? '…'}</option><option value="ordered">in order, anywhere</option><option value="anywhere">anywhere</option></NativeSelect>
                  <Button variant="link" size="sm" aria-label={`Remove pin ${p.id}`} onClick={() => void savePins(removePin(pins, p.id))}>remove</Button></li>))}
              {(pins.vo_never ?? []).map(ph => <li key={ph} className="flex items-center gap-2"><span className="rounded-control bg-danger-subtle px-1 type-caption">never</span><span className="min-w-0 flex-1">{ph}</span><Button variant="link" size="sm" aria-label={`Remove never-say ${ph}`} onClick={() => void savePins(removeNever(pins, ph))}>remove</Button></li>)}
            </ul></details>)}
        {diff.removed.length > 0 && <details className="mt-2 type-caption text-muted-foreground"><summary>{diff.removed.length} item(s) removed since the previous draft</summary><ul className="mt-1 list-disc pl-5">{diff.removed.map((it, i) => <li key={i}>{KIND[it.type].label} · clip {it.clip}: {it.text ?? it.why ?? `${it.from}–${it.to}`}</li>)}</ul></details>}
        {draft.skipped.length > 0 && <details className="mt-2 type-caption text-muted-foreground"><summary>{draft.skipped.length} clip(s) left out</summary><ul className="mt-1 list-disc pl-5">{draft.skipped.map(s => <li key={s.clip}>clip {s.clip}: {s.why}</li>)}</ul></details>}
        {draft.problems.length > 0 && <p className="mt-2 type-caption text-warning">The writer could not satisfy: {draft.problems.filter(p => !itemOf(p)).join('; ') || 'see the ⚠ marks'}</p>}
      </>)}
    </section>
  )
}
