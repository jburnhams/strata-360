import { useEffect, useRef, useState } from 'react'
import type { PlanSegment } from '../api'

const hue = (fam: string) => { let h = 0; for (const c of fam) h = (h * 31 + c.charCodeAt(0)) % 360; return h }
export const colour = (g: { family: string; hero: boolean }) => `hsl(${hue(g.family)} ${g.hero ? 75 : 45}% ${g.hero ? 48 : 52}%)`
const mmss = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').slice(-9)

/** The beats a drag of `dx` pixels moves a cut: whole beats (the planner's grid), never further than the room the cut has either way. */
export function dragBeats(dx: number, pxPerBeat: number, room: [number, number]) {
  if (!(pxPerBeat > 0)) return 0
  const b = Math.round(dx / pxPerBeat)
  return Math.max(room[0], Math.min(room[1], b)) || 0
}

// The film as a strip of its windows, in film time. Click a window to select it, shift-click another to select the run between them. When the film is the beat planner's (`editable`), the cut between
// two windows can be dragged: it snaps to whole beats inside the room the server gives (edge_room), and the server then keeps it out of the wearer's words. The arrow keys move a focused cut by one beat.
export default function FilmStrip({ segments, total, bpm, editable, busy, range, onSelect, onMoveEdge }: {
  segments: PlanSegment[]; total: number; bpm: number; editable: boolean; busy: boolean; range: [number, number] | null
  onSelect: (k: number, extend: boolean) => void; onMoveEdge: (wid: string, beats: number) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ k: number; x0: number; beats: number }>()
  const pxPerBeat = () => ((box.current?.getBoundingClientRect().width ?? 0) * (60 / bpm)) / total
  const dragRef = useRef(drag); dragRef.current = drag
  useEffect(() => {
    if (!drag) return
    const move = (e: PointerEvent) => { const d = dragRef.current; if (d) setDrag({ ...d, beats: dragBeats(e.clientX - d.x0, pxPerBeat(), segments[d.k].edge_room ?? [0, 0]) }) }
    const up = () => { const d = dragRef.current; setDrag(undefined); if (d && d.beats) onMoveEdge(segments[d.k].id, d.beats) }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  }, [drag?.k])   // eslint-disable-line react-hooks/exhaustive-deps
  const beat_s = 60 / bpm
  let at = 0
  const cuts = segments.slice(0, -1).map(g => { at += g.dur_s; return at })
  return (
    <div ref={box} className="relative h-9 w-full select-none">
      <div className="flex h-9 w-full overflow-hidden rounded-lg border border-stone-200 dark:border-stone-800" role="img" aria-label="The film, segment by segment">
        {segments.map((g, k) => {
          const inRange = !!range && k >= range[0] && k <= range[1]
          return (
            <button key={g.id} title={`${mmss(g.film_start_s)} ${short(g.clip)} ${g.technique}`} onClick={e => onSelect(k, e.shiftKey)}
              style={{ width: `${(100 * g.dur_s) / total}%`, background: colour(g), outline: inRange ? '2px solid currentColor' : 'none', outlineOffset: -2 }}
              className={`border-r border-white/70 text-[9px] leading-none text-white/90 dark:border-stone-900 ${g.locked ? 'ring-1 ring-inset ring-black/50' : ''}`}>{g.locked ? '🔒' : g.ramp ? '⏩' : ''}</button>
          )
        })}
      </div>
      {editable && cuts.map((t, k) => {
        const room = segments[k].edge_room
        if (!room || (room[0] === 0 && room[1] === 0)) return null
        const live = drag?.k === k ? drag.beats : 0, x = (100 * (t + live * beat_s)) / total
        return (
          <div key={segments[k].id} role="separator" aria-orientation="vertical" tabIndex={busy ? -1 : 0} aria-valuenow={live}
            aria-label={`cut after ${short(segments[k].clip)} at ${mmss(t)}: drag or use the arrow keys to move it by beats`}
            title={`drag to move this cut (up to ${-room[0]} beats earlier, ${room[1]} later)`}
            onPointerDown={e => { if (busy) return; e.preventDefault(); setDrag({ k, x0: e.clientX, beats: 0 }) }}
            onKeyDown={e => {
              if (busy) return
              const d = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0
              if (d && (d < 0 ? room[0] < 0 : room[1] > 0)) { e.preventDefault(); onMoveEdge(segments[k].id, d) }
            }}
            style={{ left: `calc(${x}% - 4px)` }}
            className={`absolute top-0 z-10 h-9 w-2 cursor-ew-resize rounded-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 ${drag?.k === k ? 'bg-black/60 dark:bg-white/70' : 'hover:bg-black/30 dark:hover:bg-white/40'}`}>
            {drag?.k === k && <span className="pointer-events-none absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-stone-900 px-1.5 py-0.5 text-[10px] text-white">{live > 0 ? '+' : ''}{live} beat{Math.abs(live) === 1 ? '' : 's'}</span>}
          </div>
        )
      })}
    </div>
  )
}
