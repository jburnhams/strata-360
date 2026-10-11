import { useEffect, useRef, useState, type RefObject } from 'react'
import { api, type FilmTextState, type TextCard } from '../api'
import { cardKey } from '../useFilmText'

// The film's word art drawn over the text-free preview, from the cards as they are now (the server makes each card's frames over transparency: one grid picture per card), so a change shows at once
// without rendering the film again. While a card is on, each of its words can be grabbed and dragged to a new place (or moved with the arrow keys); letting go saves the card and its picture is made again.
const FRAME_W = 480, FRAME_H = 270                                    // one frame of a card's grid (what the server draws)
const AHEAD_S = 6                                                     // a card's picture is fetched this long before it is needed

type Drag = { id: string; i: number; x: number; y: number; dx: number; dy: number }

export default function TextOverlay({ folder, video, list, reload }: { folder: string; video: RefObject<HTMLVideoElement | null>; list: FilmTextState; reload: () => void }) {
  const box = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null), imgs = useRef(new Map<string, HTMLImageElement>()), cards = useRef<TextCard[]>(list.cards), fps = useRef(list.sheet?.fps ?? 20), cols = useRef(list.sheet?.cols ?? 10)
  const [on, setOn] = useState<string[]>([]), [drag, setDrag] = useState<Drag | null>(null), [err, setErr] = useState<string>()
  cards.current = list.cards; fps.current = list.sheet?.fps ?? 20; cols.current = list.sheet?.cols ?? 10
  useEffect(() => {
    let id = 0, last = ''
    const sheet = (c: TextCard) => {
      const k = cardKey(c); let im = imgs.current.get(k)
      if (!im) { im = new Image(); im.src = api.filmTextSheetUrl(folder, c.id, k); imgs.current.set(k, im); for (const old of [...imgs.current.keys()]) if (old.startsWith(c.id + '.') && old !== k) imgs.current.delete(old) }   // (a changed card: its old picture goes)
      return im
    }
    const tick = () => {
      const v = video.current, cv = canvas.current
      if (v && cv) {
        const t = v.currentTime, act = cards.current.filter(c => t >= c.t && t < c.t + c.dur_s); cards.current.forEach(c => { if (c.t - AHEAD_S < t && t < c.t + c.dur_s) sheet(c) })
        const names = act.map(c => c.id).join(','); if (names !== last) { last = names; setOn(act.map(c => c.id)) }
        const w = cv.clientWidth, h = cv.clientHeight, ctx = w && h ? cv.getContext('2d') : null
        if (ctx) {
          if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h }
          ctx.clearRect(0, 0, w, h)
          for (const c of act) {
            const im = sheet(c)
            if (!im.complete || !im.naturalWidth) continue
            const k = Math.min(Math.max(Math.floor((t - c.t) * fps.current), 0), Math.ceil(c.dur_s * fps.current - 1e-9) - 1)
            ctx.drawImage(im, (k % cols.current) * FRAME_W, Math.floor(k / cols.current) * FRAME_H, FRAME_W, FRAME_H, 0, 0, w, h)
          }
        }
      }
      id = requestAnimationFrame(tick)
    }
    id = requestAnimationFrame(tick); return () => cancelAnimationFrame(id)
  }, [folder, video])
  const move = (c: TextCard, i: number, dx: number, dy: number) => {
    if (Math.abs(dx) < 0.003 && Math.abs(dy) < 0.003) return
    const els = c.elements.map((e, k) => k === i ? { ...e, x: Math.min(Math.max(e.x + dx, 0.06), 0.94), y: Math.min(Math.max(e.y + dy, 0.08), 0.92) } : e)
    setErr(undefined); api.saveFilmText(folder, { id: c.id, t: c.t, dur_s: c.dur_s, start_s: c.start_s, elements: els }).then(() => reload()).catch(e => setErr(e instanceof Error ? e.message : String(e)))
  }
  const rect = () => box.current?.getBoundingClientRect()
  const active = list.cards.filter(c => on.includes(c.id))
  return (
    <div ref={box} className="pointer-events-none absolute left-0 top-0 w-full" style={{ aspectRatio: '16 / 9' }}>
      <canvas ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />
      {active.map(c => c.elements.map((e, i) => {
        const b = c.boxes?.[i]; if (!b) return null
        const d = drag && drag.id === c.id && drag.i === i ? drag : null
        return (
          <div key={`${c.id}.${i}`} role="button" tabIndex={0} aria-label={`Move ${e.text}`} title={`Drag to move “${e.text}” (arrow keys too)`}
            className="pointer-events-auto absolute cursor-move touch-none rounded-sm outline-1 outline-dashed outline-white/0 hover:outline-white/80 focus-visible:outline-white"
            style={{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%`, transform: d ? `translate(${d.dx * (rect()?.width ?? 0)}px, ${d.dy * (rect()?.height ?? 0)}px)` : undefined, outlineStyle: d ? 'solid' : undefined, outlineColor: d ? 'rgba(255,255,255,0.9)' : undefined }}
            onPointerDown={ev => { ev.preventDefault(); (ev.currentTarget as HTMLElement).setPointerCapture?.(ev.pointerId); setDrag({ id: c.id, i, x: ev.clientX, y: ev.clientY, dx: 0, dy: 0 }) }}
            onPointerMove={ev => { const r = rect(); if (drag && d && r?.width && r.height) setDrag({ ...drag, dx: (ev.clientX - drag.x) / r.width, dy: (ev.clientY - drag.y) / r.height }) }}
            onPointerUp={() => { if (d) { setDrag(null); move(c, i, d.dx, d.dy) } }}
            onPointerCancel={() => setDrag(null)}
            onKeyDown={ev => { const s = ev.shiftKey ? 0.03 : 0.006, m: Record<string, [number, number]> = { ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s] }; const a = m[ev.key]; if (a) { ev.preventDefault(); move(c, i, a[0], a[1]) } }} />
        )
      }))}
      {err && <p role="alert" className="pointer-events-auto absolute bottom-10 left-2 rounded bg-red-700/90 px-2 py-0.5 text-xs text-white">{err}</p>}
    </div>
  )
}
