import { Fragment, useEffect, useMemo, useRef, useState, type UIEvent } from 'react'
import { api, type StillActive, type StillMeta } from '../api'
import { dur } from './RenderProgress'
import { clock, enlargeLabel, enlargeShort, sizeLabel } from './stillModes'

const when = (m: StillMeta) => new Date(m.rendered ?? m.modified * 1000).toLocaleString()
const mb = (b: number) => `${(b / 1e6).toFixed(1)} MB`
const BUCKETS: Record<string, string> = { decode: 'reading the video', seam: 'joining the lenses', project: 'projecting the view', upscale: 'enlarging (model)', resample: 'resampling', grade: 'exposure match', overlay: 'overlay', encode: 'encoding' }

// Every still made so far: a grid of thumbnails with a line of what each is, a photo viewer (arrow keys, Escape) with everything kept about it, and a side by side comparison of the ones ticked, at full size with the scrolling shared.
export default function StillGallery({ folder, stills, active, loading }: { folder: string; stills: StillMeta[]; active: StillActive[]; loading?: boolean }) {
  const [order, setOrder] = useState<'newest' | 'film'>('newest'), [onlyCurrent, setOnlyCurrent] = useState(false), [open, setOpen] = useState<string>(), [picked, setPicked] = useState<string[]>([])
  const shown = useMemo(() => {
    const l = stills.filter(s => !onlyCurrent || s.current)
    return [...l].sort(order === 'film' ? (a, b) => (a.t ?? a.frame / 50) - (b.t ?? b.frame / 50) || b.modified - a.modified : (a, b) => b.modified - a.modified)
  }, [stills, order, onlyCurrent])
  const idx = shown.findIndex(s => s.name === open)
  const toggle = (name: string) => setPicked(p => p.includes(name) ? p.filter(x => x !== name) : [...p, name].slice(-4))
  useEffect(() => { setPicked(p => p.filter(n => stills.some(s => s.name === n))) }, [stills])
  if (loading) return null
  if (!stills.length && !active.length) return <p className="mt-3 text-sm text-stone-500">No stills yet. Render one at the player position, or let Auto pick differing moments.</p>
  const chip = 'rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700'
  return (
    <section className="mt-3" aria-label="Still gallery">
      <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
        <h5 className="font-semibold">All stills ({stills.length})</h5>
        <label>Order <select className="rounded border border-stone-300 bg-stone-50 px-1 py-0.5 dark:border-stone-700 dark:bg-stone-950" value={order} onChange={e => setOrder(e.target.value as 'newest' | 'film')}><option value="newest">newest first</option><option value="film">by film time</option></select></label>
        {stills.some(s => !s.current) && <label><input type="checkbox" checked={onlyCurrent} onChange={e => setOnlyCurrent(e.target.checked)} /> Only the current plan</label>}
        {picked.length > 0 && <button className={chip} onClick={() => setPicked([])}>clear comparison ({picked.length})</button>}
      </div>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {active.filter(a => a.state !== 'done').map(a => (
          <li key={a.name} className="rounded-lg border border-dashed border-stone-300 p-2 text-xs dark:border-stone-700" aria-label={`Still ${a.state}`}>
            <div className="flex aspect-video items-center justify-center rounded bg-stone-100 text-stone-500 dark:bg-stone-950">{a.state === 'error' ? 'failed' : a.state === 'rendering' ? 'rendering…' : 'waiting'}</div>
            <p className="mt-1 font-medium">{a.t !== undefined ? clock(a.t) : '…'}{a.size ? ` · ${sizeLabel(a.size)}` : ''}</p>
            <p className="text-stone-500">{a.upscale ? enlargeShort(a.upscale) : ''}{a.label ? ` · ${a.label}` : ''}</p>
          </li>
        ))}
        {shown.map(s => (
          <li key={s.name} className="rounded-lg border border-stone-200 p-2 text-xs dark:border-stone-800">
            <button className="block w-full" onClick={() => setOpen(s.name)} aria-label={`Open the still at ${s.t != null ? clock(s.t) : `frame ${s.frame}`}, ${sizeLabel(s.size)}, ${enlargeShort(s.upscale) || 'made before details were kept'}`}>
              <img className="aspect-video w-full rounded bg-black object-cover" loading="lazy" src={api.filmStillThumbUrl(folder, s.name)} alt="" />
            </button>
            <p className="mt-1 font-medium">{s.t != null ? clock(s.t) : `frame ${s.frame}`}{s.size ? ` · ${sizeLabel(s.size)}` : ''}</p>
            <p className="text-stone-500">{s.legacy ? 'made before details were kept' : enlargeShort(s.upscale)}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <label className="text-stone-600 dark:text-stone-400"><input type="checkbox" checked={picked.includes(s.name)} onChange={() => toggle(s.name)} aria-label={`Compare the still at ${s.t != null ? clock(s.t) : `frame ${s.frame}`} (${enlargeShort(s.upscale) || 'unknown'})`} /> compare</label>
              {!s.current && <span className="rounded bg-amber-100 px-1 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200" title="Made from a plan, voice-over or overlay that has since changed">older plan</span>}
            </div>
          </li>
        ))}
      </ul>
      {picked.length > 1 && <Compare folder={folder} names={picked} stills={stills} />}
      {open && idx >= 0 && <Viewer folder={folder} s={shown[idx]} onClose={() => setOpen(undefined)} onStep={d => setOpen(shown[(idx + d + shown.length) % shown.length].name)} many={shown.length > 1} />}
    </section>
  )
}

function Compare({ folder, names, stills }: { folder: string; names: string[]; stills: StillMeta[] }) {
  const panes = useRef<(HTMLDivElement | null)[]>([]), busy = useRef(false)
  const sync = (i: number) => (e: UIEvent<HTMLDivElement>) => {                                    // the panes scroll together, so the same spot of each can be looked at
    if (busy.current) return
    busy.current = true; const { scrollLeft, scrollTop } = e.currentTarget; panes.current.forEach((p, k) => { if (p && k !== i) { p.scrollLeft = scrollLeft; p.scrollTop = scrollTop } }); requestAnimationFrame(() => { busy.current = false })
  }
  const list = names.map(n => stills.find(s => s.name === n)).filter((s): s is StillMeta => !!s)
  return (
    <div className="mt-3 rounded-lg border border-stone-200 p-3 dark:border-stone-800" role="region" aria-label="Comparison">
      <h5 className="mb-2 text-sm font-semibold">Comparison at full size (scrolling is shared)</h5>
      <div className={`grid gap-3 ${list.length > 2 ? 'sm:grid-cols-2' : 'sm:grid-cols-2'}`}>
        {list.map((s, i) => (
          <figure key={s.name}>
            <figcaption className="mb-1 text-xs"><strong>{s.t != null ? clock(s.t) : `frame ${s.frame}`}</strong> · {sizeLabel(s.size)} · {enlargeShort(s.upscale) || 'unknown'}{s.seconds != null ? ` · took ${dur(s.seconds)}` : ''}</figcaption>
            <div ref={el => { panes.current[i] = el }} onScroll={sync(i)} className="h-80 overflow-auto rounded border border-stone-300 bg-black dark:border-stone-700" tabIndex={0} aria-label={`Full size picture ${i + 1}`}>
              <img className="max-w-none" src={api.filmStillUrl(folder, s.name)} alt={`Still ${i + 1}: ${enlargeShort(s.upscale) || 'unknown enlarging'}`} />
            </div>
          </figure>
        ))}
      </div>
    </div>
  )
}

function Viewer({ folder, s, onClose, onStep, many }: { folder: string; s: StillMeta; onClose: () => void; onStep: (d: -1 | 1) => void; many: boolean }) {
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null; close.current?.focus()
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); else if (e.key === 'ArrowRight') onStep(1); else if (e.key === 'ArrowLeft') onStep(-1) }
    window.addEventListener('keydown', key); return () => { window.removeEventListener('keydown', key); prev?.focus?.() }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const timings = Object.entries(s.timings ?? {}).sort((a, b) => b[1] - a[1])
  const row = (k: string, v: React.ReactNode) => <div className="flex gap-2"><dt className="w-28 shrink-0 text-stone-500">{k}</dt><dd>{v}</dd></div>
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/90 p-3 text-stone-100" role="dialog" aria-modal="true" aria-label="Still viewer">
      <div className="mb-2 flex items-center gap-2 text-sm">
        <span className="font-semibold">{s.t != null ? clock(s.t) : `frame ${s.frame}`} · {sizeLabel(s.size)} · {enlargeShort(s.upscale) || 'made before details were kept'}</span>
        <span className="ml-auto flex gap-2">
          {many && <><button className="rounded border border-stone-500 px-2 py-0.5" onClick={() => onStep(-1)} aria-label="Previous still">◂</button><button className="rounded border border-stone-500 px-2 py-0.5" onClick={() => onStep(1)} aria-label="Next still">▸</button></>}
          <a className="rounded border border-stone-500 px-2 py-0.5" href={api.filmStillUrl(folder, s.name)} download={s.name}>download PNG</a>
          <button ref={close} className="rounded border border-stone-500 px-2 py-0.5" onClick={onClose}>close</button>
        </span>
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[1fr_20rem]">
        <div className="min-h-0 overflow-auto rounded bg-black"><img className="mx-auto max-h-full max-w-full object-contain" src={api.filmStillUrl(folder, s.name)} alt={`Still at ${s.t != null ? clock(s.t) : `frame ${s.frame}`}`} /></div>
        <div className="min-h-0 overflow-auto rounded bg-stone-900 p-3 text-xs">
        <dl className="space-y-1" aria-label="Details of the still">
          {row('Film time', s.t != null ? clock(s.t) : 'not kept')}
          {row('Frame', `${s.frame}${s.fps ? ` at ${s.fps} a second` : ''}`)}
          {row('Size', s.size ? `${s.size[0]}×${s.size[1]} (${sizeLabel(s.size)})` : 'not kept')}
          {row('Enlarging', enlargeLabel(s.upscale))}
          {s.model && row('Model', s.model)}
          {s.piece && row('Piece of film', s.piece === 'plain' ? 'one shot' : `${s.piece} transition`)}
          {s.shots?.map(h => <Fragment key={h.id}>{row('Shot', <span>{h.id}<br />{h.clip}{h.fov != null ? <><br />narrowest view {h.fov}°</> : null}{s.upscale && s.upscale !== 'off' ? <><br />{h.factor > 1 ? `enlarged ×${h.factor}` : `not enlarged${h.note ? ` (${h.note})` : ''}`}</> : null}</span>)}</Fragment>)}
          {row('Made', when(s))}
          {s.seconds != null && row('Took', dur(s.seconds))}
          {s.stages && row('Steps', Object.entries(s.stages).map(([k, v]) => `${k} ${dur(v)}`).join(' · '))}
          {timings.length > 0 && row('Where the time went', timings.map(([k, v]) => `${BUCKETS[k] ?? k} ${dur(v)}`).join(' · '))}
          {row('File', mb(s.bytes))}
          {row('Plan', s.current ? 'the current plan' : 'an older plan, voice-over or overlay')}
        </dl>
        <p className="pt-2 text-stone-500">{s.name}</p>
        {s.legacy && <p className="pt-1 text-stone-400">Made before the details were kept; only what the file name says is known.</p>}
        </div>
      </div>
    </div>
  )
}
