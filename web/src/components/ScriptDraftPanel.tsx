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

const KIND: Record<ScriptItem['type'], { label: string; cls: string }> = {
  vo: { label: 'narration', cls: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300' },
  clip: { label: 'you', cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' },
  gap: { label: 'gap', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300' },
  broll: { label: 'b-roll', cls: 'bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300' },
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
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">Film script</h3>
        <label className="text-xs text-stone-500">length (s) <input type="number" min={30} value={target} onChange={e => setTarget(e.target.value)} placeholder="music / automatic" className="ml-1 w-28 rounded border border-stone-300 bg-transparent px-1.5 py-1 text-sm dark:border-stone-700" /></label>
        <label className="flex items-center gap-1 text-xs text-stone-500"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> ignore the music</label>
        <button disabled={busy || st.running || !st.key_configured} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white disabled:opacity-50" onClick={() => go(!!draft)}>{st.running ? 'writing…' : draft ? 'Revise this draft' : 'Write a draft'}</button>
        {draft && <button disabled={busy || st.running || !st.key_configured} className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-stone-700" title="start again without the current draft" onClick={() => go(false)}>New draft</button>}
      </div>
      {!st.key_configured && <p className="mt-2 text-sm text-amber-700">No Gemini API key is set: add it (secrets.env or the Script panel) to write a draft.</p>}
      {st.running && st.log.length > 0 && <p className="mt-2 font-mono text-xs text-stone-500">{st.log[st.log.length - 1]}</p>}
      {!st.running && st.last_exit != null && st.last_exit !== 0 && <p className="mt-2 text-sm text-red-600">The last attempt failed: {st.log[st.log.length - 1] ?? `exit ${st.last_exit}`}</p>}
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      {draft && (
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <button disabled={busy || st.plan_running} className="rounded-lg border border-emerald-700 px-3 py-1.5 text-emerald-800 disabled:opacity-50 dark:text-emerald-300" title="turn this draft into the film's plan: your lines, the narration (spoken and timed) and b-roll, cut on the beat" onClick={() => void planIt()}>{st.plan_running ? 'planning…' : 'Make the film from this draft'}</button>
          <span className="text-xs text-stone-500">{st.plan_running ? (st.plan_log?.[st.plan_log.length - 1] ?? 'speaking the narration and planning the windows…')
            : st.plan?.source === 'script' ? `Film plan: ${st.plan.windows} windows, ${st.plan.length_s} s, from ${st.plan.script === latest ? 'this draft' : 'an older draft (make the film again to use this one)'}`
            : 'The film plan is still the beat planner’s, not this script.'}</span>
        </div>)}
      {draft && !st.plan_running && <RoughMixPlayer folder={folder} version={ver} />}
      {!st.plan_running && st.plan_exit != null && st.plan_exit !== 0 && <p className="mt-1 text-sm text-red-600">Planning failed: {st.plan_log?.[st.plan_log.length - 1] ?? `exit ${st.plan_exit}`}</p>}
      {st.plan?.source === 'script' && st.plan.warnings.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-amber-700">{st.plan.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
      {!draft ? <p className="mt-2 text-sm text-stone-500">No draft yet. The writer reads every clip, your notes and the transcript, and writes a first script you can then mark up and revise.</p> : (<>
        <div className="mt-3">
          <div className="text-base font-medium">{draft.title ?? '(untitled)'}</div>
          {draft.story && <p className="text-sm italic text-stone-500">{draft.story}</p>}
          <p className="mt-1 text-xs text-stone-500">{r?.total_s} s of {draft.target_s} s{draft.target_source ? ` (${draft.target_source})` : ''} · you {r?.clip_s} s · narration {r?.vo_s} s ({r?.vo_words} words at {draft.wpm} wpm) · b-roll {r?.broll_s} s · {r?.clips_used} clips used, {r?.clips_skipped} skipped · {draft.revised ? 'revised' : 'first draft'} {draft.created.replace('T', ' ')}{diff.added.size ? ` · ${diff.added.size} new, ${diff.removed.length} removed` : ''}</p>
        </div>
        <div ref={list}>
        <WordMarker folder={folder} onSaved={() => setVer(v => v + 1)}>
          <ol className="mt-3 space-y-1 text-sm">
            {draft.items.map((it, i) => {
              const head = it.clip !== lastClip; lastClip = it.clip; const w = warn.get(i + 1)
              return (
                <li key={i}>
                  {head && <div className="mt-2 font-mono text-xs text-stone-500">clip {it.clip}</div>}
                  <div className={`flex gap-2 rounded px-1 py-0.5 ${diff.added.has(i) ? 'bg-emerald-50 dark:bg-emerald-950/40' : ''}`}>
                    <span className={`mt-0.5 h-fit shrink-0 rounded-full px-2 text-xs ${KIND[it.type].cls}`}>{KIND[it.type].label}</span>
                    <span className="w-10 shrink-0 text-right font-mono text-xs text-stone-500">{it.seconds != null ? mmss(it.seconds) : ''}</span>
                    <span className="min-w-0 flex-1 leading-relaxed">
                      {it.type === 'vo' && (editing === i ? (
                        <span className="flex flex-col gap-1">
                          <textarea aria-label={`Narration ${i + 1}`} value={text} onChange={e => setText(e.target.value)} rows={2} className="w-full rounded border border-stone-300 bg-transparent p-1.5 text-sm dark:border-stone-700" />
                          <span className="flex gap-1"><button className="rounded bg-emerald-700 px-2 py-0.5 text-xs text-white" onClick={() => void saveEdit(i, it)}>save (pins this wording)</button><button className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => setEditing(null)}>cancel</button></span>
                        </span>
                      ) : (<>
                        <span data-vo={i} title={basisOf(it).length ? 'based on: ' + basisOf(it).join(' · ') : undefined}>{highlight(edited[i] ?? it.text ?? '', pinTexts(it.clip), pins.vo_never ?? []).map((p, k) => <span key={k} className={p.kind === 'must' ? 'rounded bg-emerald-200 dark:bg-emerald-500/40' : p.kind === 'never' ? 'rounded bg-red-200 dark:bg-red-500/40' : ''}>{p.t}</span>)}</span>
                        <button className="ml-1 text-xs text-stone-400 hover:text-stone-700" aria-label={`Edit narration ${i + 1}`} title="edit the wording: your version is kept word for word in later drafts" onClick={() => { setText(edited[i] ?? it.text ?? ''); setEditing(i) }}>✎</button>
                      </>))}
                      {it.type === 'clip' && (words(it).some(Boolean) ? words(it) : <span>{it.text}</span>)}
                      {it.type === 'broll' && <span className="text-stone-500">{it.why}</span>}
                      {it.type === 'gap' && <span className="text-stone-500">{it.kind === 'flyover' ? '3D flyover (needs your approval)' : '2D map'}, {it.seconds} s: {it.why}</span>}
                      {it.view && <span className="ml-2 text-xs text-stone-500">{it.view} view of you</span>}
                      {it.anchor && <span className="ml-2 text-xs text-stone-500" title={it.anchor.why}>anchored at {it.anchor.film_s} s</span>}
                      {diff.added.has(i) && <span className="ml-2 rounded bg-emerald-200 px-1 text-xs text-emerald-900 dark:bg-emerald-800 dark:text-emerald-100">new</span>}
                      {w && <span className="ml-2 cursor-help text-amber-700" title={w.join('\n')} aria-label={`check: ${w.join('; ')}`}>⚠</span>}
                    </span>
                  </div>
                </li>)
            })}
          </ol>
        </WordMarker>
        {vsel && (
          <div role="toolbar" aria-label="Mark the selected narration" className="fixed z-50 flex items-center gap-1 rounded-lg border border-stone-300 bg-white p-1 shadow-lg dark:border-stone-700 dark:bg-stone-900" style={{ left: Math.max(vsel.x - 120, 8), top: Math.max(vsel.y - 44, 8) }} onMouseDown={e => e.preventDefault()}>
            <button className="rounded bg-emerald-200 px-2 py-1 text-xs font-medium text-emerald-900 dark:bg-emerald-500/40 dark:text-emerald-100" title="keep exactly these words, in this clip, in every later draft" onClick={() => void pinVo(false)}>Say exactly this</button>
            <button className="rounded bg-red-200 px-2 py-1 text-xs font-medium text-red-900 dark:bg-red-500/40 dark:text-red-100" title="never say these words" onClick={() => void pinVo(true)}>Never say</button>
          </div>)}
        </div>
        {((pins.vo ?? []).length > 0 || (pins.vo_never ?? []).length > 0) && (
          <details className="mt-3 text-sm"><summary className="cursor-pointer text-xs text-stone-500">Your narration pins ({(pins.vo ?? []).length + (pins.vo_never ?? []).length})</summary>
            <ul className="mt-1 space-y-1">
              {(pins.vo ?? []).map((p: VoPin) => (
                <li key={p.id} className="flex flex-wrap items-center gap-2"><span className="rounded bg-emerald-200 px-1 text-xs dark:bg-emerald-500/40">say</span><span className="min-w-0 flex-1">{p.text}</span>
                  <select aria-label={`Where to say ${p.id}`} value={p.mode} onChange={e => void savePins(setMode(pins, p.id, e.target.value as VoPin['mode'], p.clip ?? draft.items.find(x => x.type === 'vo' && x.text?.includes(p.text))?.clip))} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 text-xs dark:border-stone-700">
                    <option value="clip">in clip {p.clip ?? '…'}</option><option value="ordered">in order, anywhere</option><option value="anywhere">anywhere</option></select>
                  <button className="text-xs underline" aria-label={`Remove pin ${p.id}`} onClick={() => void savePins(removePin(pins, p.id))}>remove</button></li>))}
              {(pins.vo_never ?? []).map(ph => <li key={ph} className="flex items-center gap-2"><span className="rounded bg-red-200 px-1 text-xs dark:bg-red-500/40">never</span><span className="min-w-0 flex-1">{ph}</span><button className="text-xs underline" aria-label={`Remove never-say ${ph}`} onClick={() => void savePins(removeNever(pins, ph))}>remove</button></li>)}
            </ul></details>)}
        {diff.removed.length > 0 && <details className="mt-2 text-xs text-stone-500"><summary>{diff.removed.length} item(s) removed since the previous draft</summary><ul className="mt-1 list-disc pl-5">{diff.removed.map((it, i) => <li key={i}>{KIND[it.type].label} · clip {it.clip}: {it.text ?? it.why ?? `${it.from}–${it.to}`}</li>)}</ul></details>}
        {draft.skipped.length > 0 && <details className="mt-2 text-xs text-stone-500"><summary>{draft.skipped.length} clip(s) left out</summary><ul className="mt-1 list-disc pl-5">{draft.skipped.map(s => <li key={s.clip}>clip {s.clip}: {s.why}</li>)}</ul></details>}
        {draft.problems.length > 0 && <p className="mt-2 text-xs text-amber-700">The writer could not satisfy: {draft.problems.filter(p => !itemOf(p)).join('; ') || 'see the ⚠ marks'}</p>}
      </>)}
    </section>
  )
}
