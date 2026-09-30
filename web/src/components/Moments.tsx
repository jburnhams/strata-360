import { useState } from 'react'
import type { Candidate, Unusable } from '../api'

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
type Item = { start: number; end: number; usable: boolean; c?: Candidate; u?: Unusable }

const KIND: Record<string, [string, string]> = { span: ['whole', 'the whole usable stretch'], best: ['best', 'the steadiest, best-looking part of a stretch'], speech: ['you talk', 'you speaking: dialogue, steady framing'], person: ['person', 'other people in view: framed on them'], you: ['you', 'you in view'], scene: ['scene', 'one setting of a stretch'] }

// The clip's footage: grey = not usable (only camera shake, a blocked lens or bad exposure), green = usable. Below, the candidates: overlapping ways to see that footage (the whole stretch, its best part,
// you talking, people in view ...), best first. The film uses one of them for any moment. Hover for the reasons and the numbers.
export default function Moments({ duration, usable, unusable }: { duration: number; usable: Candidate[] | null; unusable?: Unusable[] | null; thresholds?: { usable_score: number; min_len_s: number; max_stretch_s: number } | null }) {
  const [tip, setTip] = useState<{ it: Item; x: number; y: number }>()
  if (!usable) return <p className="text-sm text-stone-500">Moments are worked out once the other stages have finished.</p>
  const spans = usable.filter(c => (c.kind ?? 'span') === 'span'), bad = unusable ?? []
  const items: Item[] = [...usable.map(c => ({ start: c.start_s, end: c.end_s, usable: true, c } as Item)), ...bad.map(u => ({ start: u.start_s, end: u.end_s, usable: false, u } as Item))].sort((a, b) => a.start - b.start || (a.c?.priority ?? 0) - (b.c?.priority ?? 0))
  const total = spans.length ? spans.reduce((a, c) => a + c.end_s - c.start_s, 0) : usable.reduce((a, c) => a + c.end_s - c.start_s, 0)
  const hover = (it: Item) => ({ onMouseEnter: (e: React.MouseEvent) => setTip({ it, x: e.clientX, y: e.clientY }), onMouseMove: (e: React.MouseEvent) => setTip({ it, x: e.clientX, y: e.clientY }), onMouseLeave: () => setTip(undefined) })
  const strip = [...spans.map(c => ({ start: c.start_s, end: c.end_s, usable: true, c } as Item)), ...bad.map(u => ({ start: u.start_s, end: u.end_s, usable: false, u } as Item))].sort((a, b) => a.start - b.start)
  return (
    <div>
      <div className="relative mb-2 h-5 w-full overflow-hidden rounded bg-stone-200 dark:bg-stone-800">
        {strip.map((it, i) => (
          <div key={i} {...hover(it)} style={{ position: 'absolute', left: `${(100 * it.start) / duration}%`, width: `${(100 * (it.end - it.start)) / duration}%` }} className={`h-full border-r border-white/60 dark:border-stone-900 ${it.usable ? 'bg-emerald-600' : 'bg-stone-400 dark:bg-stone-600'}`} />
        ))}
      </div>
      <p className="mb-2 text-xs text-stone-500">{Math.round(total)} s of {Math.round(duration)} s usable. Footage is only unusable when the camera shake is over about 57°/s, the lens is blocked or fogged, or the picture is badly exposed: everything else can be used, and which part and how is the film planner's choice. The rows below are {usable.length} overlapping ways of seeing it, best first (number = rank).</p>
      {items.map((it, i) => (
        <div key={i} {...hover(it)} className="flex items-center gap-2 py-0.5 text-sm">
          <span className="w-24 shrink-0 font-mono text-xs text-stone-500">{fmt(it.start)}–{fmt(it.end)}</span>
          {it.usable && it.c ? (
            <>
              <span title={KIND[it.c.kind ?? 'span']?.[1]} className="w-16 shrink-0 rounded bg-stone-100 px-1 text-center text-xs dark:bg-stone-800">{KIND[it.c.kind ?? 'span']?.[0]}</span>
              <span className="w-6 shrink-0 text-right text-xs text-stone-500" title="rank in this clip">{it.c.priority ?? ''}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"><div className="h-full bg-emerald-600" style={{ width: `${it.c.quality * 100}%` }} /></div>
              {it.c.features.speech > 0.5 && <span title="you speak">💬</span>}
            </>
          ) : <span className="flex-1 truncate text-xs text-stone-500">not usable: {it.u?.reasons.join(', ')}</span>}
        </div>
      ))}
      {tip && (() => { const { it } = tip, left = Math.min(tip.x + 14, window.innerWidth - 330), top = Math.min(tip.y + 14, window.innerHeight - 230); return (
        <div className="pointer-events-none fixed z-40 w-80 rounded-lg border border-stone-300 bg-white p-2.5 text-xs shadow-lg dark:border-stone-700 dark:bg-stone-900" style={{ left, top }}>
          <div className="mb-1 font-medium">{fmt(it.start)}–{fmt(it.end)} ({Math.round(it.end - it.start)} s) · {it.usable ? 'usable' : 'not usable'}</div>
          {it.usable && it.c?.why ? (<>
            <div>score {it.c.why.score} · steadiness {Math.round(it.c.why.steadiness * 100)}% (shake {it.c.why.shake_dps}°/s) · exposure {Math.round(it.c.why.exposure_ok * 100)}% ok · scenic {it.c.why.scenic} · lens blocked {Math.round(it.c.why.lens_blocked * 100)}%</div>
            <div className="mt-1 text-stone-500">{it.c.settings.join(', ') || 'setting unknown'} · about {it.c.people} people · {it.c.why.speech ? 'you speak' : it.c.why.chatter > 0.5 ? 'other voices' : 'no speech'}</div>
            <div className="mt-1 text-stone-500">starts: {it.c.why.starts_because}<br />ends: {it.c.why.ends_because ?? '—'}</div>
          </>) : it.u && (<>
            <div>{it.u.reasons.join('; ')}</div>{it.u.detail && <div className="mt-1 text-stone-500">{it.u.detail}</div>}
            <div className="mt-1 text-stone-500">score {String(it.u.stats.score)} · steadiness {Math.round(Number(it.u.stats.steadiness) * 100)}% (shake {String(it.u.stats.shake_dps)}°/s) · exposure {Math.round(Number(it.u.stats.exposure_ok) * 100)}% ok</div>
            <div className="mt-1 text-stone-500">starts: {it.u.starts_because}<br />ends: {it.u.ends_because ?? '—'}</div>
          </>)}
        </div>) })()}
    </div>
  )
}
