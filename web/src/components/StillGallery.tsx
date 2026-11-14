import { Fragment, useEffect, useMemo, useRef, useState, type UIEvent } from 'react'
import { api, type StillActive, type StillMeta } from '../api'
import { dur } from './RenderProgress'
import { clock, enlargeLabel, enlargeShort, sizeLabel } from './stillModes'
import { Button, Checkbox, Lightbox, NativeSelect, type LightboxItem } from 'strata-react'

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
  const items = useMemo<LightboxItem[]>(() => shown.map(s => ({ id: s.name, src: api.filmStillUrl(folder, s.name), label: `Still at ${s.t != null ? clock(s.t) : `frame ${s.frame}`}`, natural: s.size ? [s.size[0], s.size[1]] as const : undefined })), [shown, folder])
  const toggle = (name: string) => setPicked(p => p.includes(name) ? p.filter(x => x !== name) : [...p, name].slice(-4))
  useEffect(() => { setPicked(p => p.filter(n => stills.some(s => s.name === n))) }, [stills])
  if (loading) return null
  if (!stills.length && !active.length) return <p className="mt-3 type-body-sm text-muted-foreground">No stills yet. Render one at the player position, or let Auto pick differing moments.</p>
  return (
    <section className="mt-3" aria-label="Still gallery">
      <div className="mb-2 flex flex-wrap items-center gap-3 type-body-sm">
        <h5 className="font-semibold">All stills ({stills.length})</h5>
        <label>Order <NativeSelect size="sm" value={order} onChange={e => setOrder(e.target.value as 'newest' | 'film')}><option value="newest">newest first</option><option value="film">by film time</option></NativeSelect></label>
        {stills.some(s => !s.current) && <Checkbox label="Only the current plan" checked={onlyCurrent} onCheckedChange={(checked: boolean) => setOnlyCurrent(checked)} />}
        {picked.length > 0 && <Button variant="outline" size="sm" onClick={() => setPicked([])}>clear comparison ({picked.length})</Button>}
      </div>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {active.filter(a => a.state !== 'done').map(a => (
          <li key={a.name} className="rounded-surface border border-dashed border-border p-2 type-caption" aria-label={`Still ${a.state}`}>
            <div className="flex aspect-video items-center justify-center rounded-control bg-muted text-muted-foreground">{a.state === 'error' ? 'failed' : a.state === 'rendering' ? 'rendering…' : 'waiting'}</div>
            <p className="mt-1 font-medium">{a.t !== undefined ? clock(a.t) : '…'}{a.size ? ` · ${sizeLabel(a.size)}` : ''}</p>
            <p className="text-muted-foreground">{a.upscale ? enlargeShort(a.upscale) : ''}{a.label ? ` · ${a.label}` : ''}</p>
          </li>
        ))}
        {shown.map(s => (
          <li key={s.name} className="rounded-surface border border-border p-2 type-caption">
            <Button variant="ghost" className="block w-full" onClick={() => setOpen(s.name)} aria-label={`Open the still at ${s.t != null ? clock(s.t) : `frame ${s.frame}`}, ${sizeLabel(s.size)}, ${enlargeShort(s.upscale) || 'made before details were kept'}`}>
              <img className="aspect-video w-full rounded-control bg-black object-cover" loading="lazy" src={api.filmStillThumbUrl(folder, s.name)} alt="" />
            </Button>
            <p className="mt-1 font-medium">{s.t != null ? clock(s.t) : `frame ${s.frame}`}{s.size ? ` · ${sizeLabel(s.size)}` : ''}</p>
            <p className="text-muted-foreground">{s.legacy ? 'made before details were kept' : enlargeShort(s.upscale)}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Checkbox label={`Compare the still at ${s.t != null ? clock(s.t) : `frame ${s.frame}`} (${enlargeShort(s.upscale) || 'unknown'})`} hideLabel checked={picked.includes(s.name)} onCheckedChange={() => toggle(s.name)} detail="compare" />
              {!s.current && <span className="rounded-control bg-warning-subtle px-1 text-warning" title="Made from a plan, voice-over or overlay that has since changed">older plan</span>}
            </div>
          </li>
        ))}
      </ul>
      {picked.length > 1 && <Compare folder={folder} names={picked} stills={stills} />}
      <Lightbox title="Stills" items={items} index={Math.max(idx, 0)} onIndexChange={i => setOpen(shown[i]?.name)} open={open !== undefined && idx >= 0} onOpenChange={o => { if (!o) setOpen(undefined) }} missing="This still could not be loaded." detailsLabel="Details of the still"
        details={item => { const m = shown.find(x => x.name === item.id); return m ? <Details folder={folder} s={m} /> : null }} />
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
    <div className="mt-3 rounded-surface border border-border p-3" role="region" aria-label="Comparison">
      <h5 className="mb-2 type-body-sm font-semibold">Comparison at full size (scrolling is shared)</h5>
      <div className={`grid gap-3 ${list.length > 2 ? 'sm:grid-cols-2' : 'sm:grid-cols-2'}`}>
        {list.map((s, i) => (
          <figure key={s.name}>
            <figcaption className="mb-1 type-caption"><strong>{s.t != null ? clock(s.t) : `frame ${s.frame}`}</strong> · {sizeLabel(s.size)} · {enlargeShort(s.upscale) || 'unknown'}{s.seconds != null ? ` · took ${dur(s.seconds)}` : ''}</figcaption>
            <div ref={el => { panes.current[i] = el }} onScroll={sync(i)} className="h-80 overflow-auto rounded-control border border-border bg-black" tabIndex={0} aria-label={`Full size picture ${i + 1}`}>
              <img className="max-w-none" src={api.filmStillUrl(folder, s.name)} alt={`Still ${i + 1}: ${enlargeShort(s.upscale) || 'unknown enlarging'}`} />
            </div>
          </figure>
        ))}
      </div>
    </div>
  )
}

function Details({ folder, s }: { folder: string; s: StillMeta }) {
  const timings = Object.entries(s.timings ?? {}).sort((a, b) => b[1] - a[1])
  const row = (k: string, v: React.ReactNode) => <div className="flex gap-2"><dt className="w-28 shrink-0 text-muted-foreground">{k}</dt><dd>{v}</dd></div>
  return (
    <div className="type-caption">
      <a className="mb-2 inline-block rounded-control border border-input px-2 py-0.5" href={api.filmStillUrl(folder, s.name)} download={s.name}>download PNG</a>
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
        <p className="pt-2 text-muted-foreground">{s.name}</p>
        {s.legacy && <p className="pt-1 text-muted-foreground">Made before the details were kept; only what the file name says is known.</p>}
    </div>
  )
}
