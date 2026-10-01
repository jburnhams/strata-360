import { useEffect, useMemo, useState } from 'react'
import { api, type ScriptItem, type Seg } from '../api'
import { usePoll } from '../usePoll'
import { usedSet } from '../marks'
import { diffDrafts } from '../scriptDiff'
import { PanelSkeleton } from './Skeleton'
import Phrase from './Phrase'
import WordMarker from './WordMarker'

const KIND: Record<ScriptItem['type'], { label: string; cls: string }> = {
  vo: { label: 'narration', cls: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300' },
  clip: { label: 'you', cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' },
  broll: { label: 'b-roll', cls: 'bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300' },
}
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
const itemOf = (msg: string) => { const m = msg.match(/^item (\d+):/); return m ? Number(m[1]) : null }

// The whole-race script, as written by the script writer from everything it knows: your own lines (words coloured as in the transcript: select words to mark them), narration, and b-roll, in film order.
// "Revise" sends the draft back with your marks and pins and gets a new draft that keeps everything they do not touch; items new since the previous draft are flagged.
export default function ScriptDraftPanel({ folder }: { folder: string }) {
  const [ver, setVer] = useState(0)
  const st = usePoll(() => api.script2(folder), 4000, [folder, ver])
  const tr = usePoll(() => api.transcript(folder), 30000, [folder, ver])
  const [prevName, setPrevName] = useState<string | null>(null)
  const [prevItems, setPrevItems] = useState<ScriptItem[]>()
  const [target, setTarget] = useState(''), [auto, setAuto] = useState(false), [err, setErr] = useState<string>(), [busy, setBusy] = useState(false)
  const draft = st?.draft ?? null
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
      {!draft ? <p className="mt-2 text-sm text-stone-500">No draft yet. The writer reads every clip, your notes and the transcript, and writes a first script you can then mark up and revise.</p> : (<>
        <div className="mt-3">
          <div className="text-base font-medium">{draft.title ?? '(untitled)'}</div>
          {draft.story && <p className="text-sm italic text-stone-500">{draft.story}</p>}
          <p className="mt-1 text-xs text-stone-500">{r?.total_s} s of {draft.target_s} s{draft.target_source ? ` (${draft.target_source})` : ''} · you {r?.clip_s} s · narration {r?.vo_s} s ({r?.vo_words} words at {draft.wpm} wpm) · b-roll {r?.broll_s} s · {r?.clips_used} clips used, {r?.clips_skipped} skipped · {draft.revised ? 'revised' : 'first draft'} {draft.created.replace('T', ' ')}{diff.added.size ? ` · ${diff.added.size} new, ${diff.removed.length} removed` : ''}</p>
        </div>
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
                      {it.type === 'vo' && <span title={it.basis?.length ? 'based on: ' + it.basis.join(' · ') : undefined}>{it.text}</span>}
                      {it.type === 'clip' && (words(it).some(Boolean) ? words(it) : <span>{it.text}</span>)}
                      {it.type === 'broll' && <span className="text-stone-500">{it.why}</span>}
                      {diff.added.has(i) && <span className="ml-2 rounded bg-emerald-200 px-1 text-xs text-emerald-900 dark:bg-emerald-800 dark:text-emerald-100">new</span>}
                      {w && <span className="ml-2 cursor-help text-amber-700" title={w.join('\n')} aria-label={`check: ${w.join('; ')}`}>⚠</span>}
                    </span>
                  </div>
                </li>)
            })}
          </ol>
        </WordMarker>
        {diff.removed.length > 0 && <details className="mt-2 text-xs text-stone-500"><summary>{diff.removed.length} item(s) removed since the previous draft</summary><ul className="mt-1 list-disc pl-5">{diff.removed.map((it, i) => <li key={i}>{KIND[it.type].label} · clip {it.clip}: {it.text ?? it.why ?? `${it.from}–${it.to}`}</li>)}</ul></details>}
        {draft.skipped.length > 0 && <details className="mt-2 text-xs text-stone-500"><summary>{draft.skipped.length} clip(s) left out</summary><ul className="mt-1 list-disc pl-5">{draft.skipped.map(s => <li key={s.clip}>clip {s.clip}: {s.why}</li>)}</ul></details>}
        {draft.problems.length > 0 && <p className="mt-2 text-xs text-amber-700">The writer could not satisfy: {draft.problems.filter(p => !itemOf(p)).join('; ') || 'see the ⚠ marks'}</p>}
      </>)}
    </section>
  )
}
