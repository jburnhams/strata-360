import { api, type Photo } from '../api'

const when = (t: number, tz: string) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(t * 1000)).replace(',', '') } catch { return new Date(t * 1000).toISOString() } }
const hms = (s: number) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`

/** What the photo analysis found (the clip stages that make sense for a photo): the place, the scene and its scenery score, who is in it, the light and sharpness, and a link to the picture with the race overlay. */
function Analysis({ folder, id, a }: { folder: string; id: string; a: NonNullable<Photo['analysis']> }) {
  if (!a.stages.length) return null
  const bits = [a.place, a.setting && `${a.setting}${a.weather && a.weather !== 'unknown' ? `, ${a.weather}` : ''}`, a.scenery != null && `scenery ${a.scenery}/10${a.clarity != null ? `, clarity ${a.clarity}/5` : ''}`,
    a.people != null && (a.people === 0 ? 'nobody in it' : `${a.people} ${a.people === 1 ? 'person' : 'people'}${a.me ? ', you among them' : ''}${a.me && a.face_clear != null ? (a.face_clear ? ' (face clear)' : ' (face not clear)') : ''}`),
    a.exposure && a.exposure !== 'ok' && `looks ${a.exposure}`, a.quality && a.quality !== 'ok' && `picture ${a.quality}`].filter(Boolean)
  return (
    <div data-analysis="" className="space-y-0.5">
      {a.description && <div className="italic text-stone-600 dark:text-stone-400">{a.description}</div>}
      {bits.length > 0 && <div className="text-stone-600 dark:text-stone-400">{bits.join(' · ')}</div>}
      {a.tags && a.tags.length > 0 && <div className="flex flex-wrap gap-1">{a.tags.map(t => <span key={t} className="rounded-full bg-stone-200 px-1.5 text-[10px] dark:bg-stone-800">{t}</span>)}</div>}
      {a.overlay && <a className="text-emerald-700 underline dark:text-emerald-400" target="_blank" rel="noreferrer" href={api.photoOverlay(folder, id)}>with the race overlay</a>}
    </div>
  )
}

/** One photo: its picture (a JPEG copy, click for the larger one), when it was taken and how that was worked out, where, and a warning when its own position and the run's disagree. */
export function PhotoCard({ folder, p, tz, onOpen, onRemove }: { folder: string; p: Photo; tz: string; onOpen?: (w: NonNullable<Photo['where']>) => void; onRemove?: () => void }) {
  return (
    <figure data-photo={p.id} className="w-56 text-xs">
      <a href={api.photoFile(folder, p.id)} target="_blank" rel="noreferrer" title={`${p.name} (${p.width} x ${p.height}): click for the larger picture`}>
        <img loading="lazy" src={api.photoThumb(folder, p.id, 480)} alt={p.name} className="h-40 w-56 rounded object-cover" /></a>
      <figcaption className="mt-1 space-y-0.5">
        <div className="font-medium">{when(p.taken_utc, tz)}</div>
        <div className="text-stone-500" title={`how the time was worked out: ${p.time_source}`}>{p.track ? `${hms(p.track.elapsed_s)} into the race · km ${p.track.km}` : 'not on the run'} · {p.time_source}</div>
        <div className="text-stone-500">{p.loc ? `${p.loc.lat.toFixed(4)}, ${p.loc.lon.toFixed(4)} (${p.loc.source})` : 'no position'}{p.apart_m != null ? ` · ${p.apart_m} m from the run` : ''}</div>
        {p.analysis && <Analysis folder={folder} id={p.id} a={p.analysis} />}
        {p.flag && <div role="alert" className="text-amber-700 dark:text-amber-400">⚠ {p.flag}</div>}
        <div className="flex gap-3">
          {onOpen && p.where && <button className="text-emerald-700 underline dark:text-emerald-400" onClick={() => onOpen(p.where!)}>{p.where.kind === 'gap' ? `gap ${p.where.id}` : `clip ${p.where.id.replace(/^CAM_\d+_(\d+)_D$/, '$1')}`}</button>}
          {onOpen && !p.where && <span className="text-stone-500">between clips</span>}
          {onRemove && <button aria-label={`Remove ${p.name}`} className="text-stone-500 underline" onClick={onRemove}>Remove</button>}
        </div>
      </figcaption>
    </figure>
  )
}

/** The photos taken during a clip or gap (their time falls in it), for its page. */
export default function PhotoStrip({ folder, photos, tz, kind, id }: { folder: string; photos?: Photo[]; tz: string; kind: 'clip' | 'gap'; id: string }) {
  const mine = (photos ?? []).filter(p => p.where?.kind === kind && p.where.id === id)
  if (!mine.length) return null
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <h3 className="mb-2 text-sm font-semibold">Photos taken {kind === 'gap' ? 'in this gap' : 'during this clip'} <span className="font-normal text-stone-500">({mine.length})</span></h3>
      <div className="flex flex-wrap gap-4">{mine.map(p => <PhotoCard key={p.id} folder={folder} p={p} tz={tz} />)}</div>
    </section>
  )
}
