import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type EditState, type RefitReport, type VoiceTimeline, type VoiceTimelineLine } from '../api'

type Plan = NonNullable<EditState['plan']>
const roleName = { vo: 'narration', clip: 'you', broll: 'b-roll' } as const
const pct = (x: number, total: number) => `${(100 * Math.max(0, x)) / total}%`

/** The script's blocks: runs of consecutive windows of one script item. */
export function blocksOf(plan: Plan) {
  const out: { item: number; role?: 'clip' | 'vo' | 'broll'; start: number; dur: number; windows: number }[] = []
  for (const g of plan.segments) {
    if (g.item === undefined || g.item === null) continue
    const last = out[out.length - 1]
    if (last && last.item === g.item && Math.abs(last.start + last.dur - g.film_start_s) < 0.01) { last.dur += g.dur_s; last.windows += 1 } else out.push({ item: g.item, role: g.role, start: g.film_start_s, dur: g.dur_s, windows: 1 })
  }
  return out
}

/** What re-fitting did, in a sentence. */
export function refitText(r: RefitReport | null | undefined) {
  if (!r) return 'The take is saved.'
  const n = (r.item ?? 0) + 1, d = Math.abs(r.delta_s ?? 0), b = Math.abs(r.beats ?? 0)
  if (r.mode === 'refit') return `Item ${n} ${(r.delta_s ?? 0) > 0 ? 'grew' : 'shrank'} by ${d.toFixed(1)} s (${b} beat${b === 1 ? '' : 's'}); every other shot is unchanged.`
  if (r.mode === 'same') return `The new take fits item ${n}'s picture as it is: nothing moved.`
  if (r.mode === 'replan') return 'The line is spoken over a generated clip, so the film was planned again.'
  return `The take is saved, but the film was not re-fitted: ${r.reason ?? 'unknown reason'}.`
}

// The voice-over over the film's windows (V6): the narration lines with their measured lengths, the script's blocks as bands, the music's beats as ticks and the cuts that could not land on one.
// Record a line again from here: only its block (and the cut after it) is re-fitted to the new take.
export default function VoiceTrack({ folder, plan, onChanged, children }: { folder: string; plan: Plan; onChanged: () => void; children: ReactNode }) {
  const [v, setV] = useState<VoiceTimeline>()
  const [sel, setSel] = useState<VoiceTimelineLine>()
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string[]>()
  const [err, setErr] = useState<string>()
  const load = () => api.voiceTimeline(folder).then(setV).catch(e => setErr((e as Error).message))
  useEffect(() => { void load() }, [folder, plan])   // eslint-disable-line react-hooks/exhaustive-deps
  const blocks = useMemo(() => blocksOf(plan), [plan])
  const bars = useMemo(() => new Set(v?.bars ?? []), [v])
  const total = plan.film.length_s || 1, off = plan.beat_sync?.off_beat ?? []
  const line = sel && v?.lines.find(l => l.seg === sel.seg)

  const record = async (l: VoiceTimelineLine) => {
    setErr(undefined); setMsg(undefined)
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true }); const mr = new MediaRecorder(s); const parts: Blob[] = []
      mr.ondataavailable = e => parts.push(e.data)
      mr.onstop = async () => {
        s.getTracks().forEach(x => x.stop()); setRec(null); setBusy(true)
        try { const r = await api.recordVoiceover(folder, l.seg, new Blob(parts, { type: mr.mimeType })); setMsg([refitText(r.refit), ...(r.refit?.warnings ?? [])]); await api.buildVoiceover(folder); onChanged(); await load() }
        catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
      }
      mr.start(); setRec(mr)
    } catch { setErr('The browser could not use a microphone (it needs permission, and https or localhost).') }
  }

  if (!v) return <>{children}{err && <p className="text-sm text-red-600">{err}</p>}</>
  return (
    <div className="space-y-1">
      {v.lines.length > 0 && (
        <div className="relative h-6 w-full" role="group" aria-label="Narration lines">
          {v.lines.map((l, i) => (
            <button key={String(l.seg)} aria-label={`Line ${i + 1}: ${l.text}`} onClick={() => { setSel(l); setMsg(undefined) }}
              title={`${l.text}\n${l.speak_s.toFixed(1)} s of speech${l.estimated ? ' (estimated from the words)' : ''} in ${l.room_s.toFixed(1)} s of picture · ${l.source === 'recorded' ? 'your recording' : 'the voice'}${l.fit === 'over' ? ` · too long by ${l.overrun_s.toFixed(1)} s` : ''}`}
              style={{ left: pct(l.start_s, total), width: pct(Math.max(l.speak_s, 0.2), total) }}
              className={`absolute top-1 h-4 truncate rounded-sm px-0.5 text-left text-[9px] leading-4 text-white ${l.fit === 'over' ? 'bg-red-600' : l.source === 'recorded' ? 'bg-violet-600' : l.estimated ? 'bg-sky-300' : 'bg-sky-600'} ${line?.seg === l.seg ? 'ring-2 ring-stone-900 dark:ring-white' : ''}`}>{l.text}</button>
          ))}
        </div>
      )}
      {blocks.length > 0 && (
        <div className="relative h-4 w-full" role="list" aria-label="Script blocks">
          {blocks.map((b, i) => (
            <span key={`${b.item}-${i}`} role="listitem" aria-label={`Item ${b.item + 1}: ${b.role ? roleName[b.role] : 'picture'}, ${b.dur.toFixed(1)} s`} title={`item ${b.item + 1} · ${b.role ? roleName[b.role] : 'picture'} · ${b.windows} window${b.windows === 1 ? '' : 's'} · ${b.dur.toFixed(1)} s`}
              style={{ left: pct(b.start, total), width: pct(b.dur, total) }}
              className={`absolute top-0 h-4 truncate border-x border-white px-0.5 text-[9px] leading-4 dark:border-stone-900 ${b.role === 'vo' ? 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300' : b.role === 'clip' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300'}`}>{b.item + 1}</span>
          ))}
        </div>
      )}
      {children}
      <div className="relative h-3 w-full">
        {v.beats.length > 0 && (
          <svg className="absolute inset-0 h-full w-full text-stone-400 dark:text-stone-600" viewBox={`0 0 ${total} 10`} preserveAspectRatio="none" role="img" aria-label={`${v.beats.length} beats and ${v.bars.length} bar lines${v.synced ? ' of the music' : ' of the plan\'s tempo'}`}>
            {v.beats.map(t => <line key={t} x1={t} x2={t} y1={0} y2={bars.has(t) ? 10 : 5} stroke="currentColor" strokeWidth={bars.has(t) ? 1.5 : 1} vectorEffect="non-scaling-stroke" />)}
          </svg>
        )}
        {off.map(o => <span key={o.cut} role="img" aria-label={`Cut ${o.cut} is ${Math.round(o.off_ms)} ms off the beat: ${o.why}`} title={`cut ${o.cut} (${o.film_s.toFixed(1)} s) is ${Math.round(o.off_ms)} ms off the beat: ${o.why}`}
          style={{ left: pct(o.film_s, total) }} className="absolute top-0 -translate-x-1/2 text-[10px] leading-3 text-red-600">▲</span>)}
      </div>
      {line && (
        <div className="rounded-lg border border-stone-200 p-2 text-xs dark:border-stone-800">
          <p className="mb-1 text-sm">{line.text}</p>
          <p className="mb-1 text-stone-500">{line.speak_s.toFixed(1)} s of speech{line.estimated ? ' (estimated from the words: not spoken yet)' : ''} in {line.room_s.toFixed(1)} s of picture · {line.source === 'recorded' ? 'your recording' : 'the voice'}{line.fit === 'over' ? <span className="text-red-600"> · too long by {line.overrun_s.toFixed(1)} s</span> : ''}</p>
          <div className="flex flex-wrap items-center gap-2">
            {!line.estimated && <audio controls className="h-8" src={api.voiceoverAudio(folder, line.seg, line.source)} aria-label="This line's take" />}
            {rec ? <button className="rounded bg-red-600 px-2 py-1 text-white" onClick={() => rec.stop()}>■ stop</button>
              : <button disabled={busy} className="rounded border border-stone-300 px-2 py-1 disabled:opacity-40 dark:border-stone-700" onClick={() => record(line)}>● {line.has_recording ? 'record again' : 'record'}</button>}
            {busy && <span className="text-stone-500">fitting the film to the new take…</span>}
          </div>
        </div>
      )}
      {msg?.map(m => <p key={m} className="text-xs text-stone-600 dark:text-stone-400">{m}</p>)}
      {err && <p className="text-sm text-red-600">{err}</p>}
    </div>
  )
}
