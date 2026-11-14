import { useState } from 'react'
import { api, type DetectedObject, type ObjectsInfo, type Region } from '../api'
import { Button, Checkbox, Tooltip } from 'strata-react'

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const LIMIT = 12
export type Look = { lon: number; lat: number; fov: number; t: number }
export type Hide = (o: DetectedObject, scope: 'object' | 'label', hide: boolean) => void
const WHY: Record<string, string> = { stop: 'on the list of what is not a thing (ground, body parts)', scenery: 'on the list of scenery', label: 'hidden by you: every one with this name', object: 'hidden by you: this one' }

/** A direction in words: the compass-style bearing of the world-locked frame (0° is where the picture's middle looks) and how far above or below the horizon. */
export const where = (lon: number, lat: number) => `${Math.round(((lon % 360) + 360) % 360)}°${Math.abs(lat) >= 5 ? `, ${Math.round(Math.abs(lat))}° ${lat > 0 ? 'up' : 'down'}` : ''}`
/** The field of view that frames something of the given size: about four times as wide, between 40° and 100°. */
export const framing = (deg: number) => Math.max(40, Math.min(100, Math.round(deg * 4)))
/** The field of view that shows a whole area of snow or water: its width, or its height times the picture's 16:9, with a small margin; between 60° and 140°. */
export const framingArea = (w: number, h: number) => Math.max(60, Math.min(140, Math.round(Math.max(w, h * (16 / 9)) * 1.15)))

const Row = ({ o, folder, clip, onLook, onHide }: { o: DetectedObject; folder: string; clip: string; onLook: (l: Look) => void; onHide?: Hide }) => {
  const name = o.label ?? o.yoloe, differs = o.source === 'vlm' && o.yoloe && !name.toLowerCase().includes(o.yoloe.toLowerCase())
  return (
    <li className={`flex items-center gap-3 py-1.5 type-body-sm ${o.hidden ? 'opacity-60' : ''}`}>
      {o.crop ? <img src={api.objectUrl(folder, clip, o.id)} alt="" loading="lazy" className="h-12 w-12 flex-none rounded-control object-cover" /> : <div className="h-12 w-12 flex-none rounded-control bg-muted" aria-hidden="true" />}
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{name}{o.source === 'detector' && <span className="ml-1 type-caption font-normal text-muted-foreground">(trusted detector word)</span>}</div>
        <div className="type-caption text-muted-foreground">{where(o.lon, o.lat)} · {o.deg.toFixed(1)}° wide · in view {fmt(o.seen[0] ?? o.best_t)}{o.seen.length > 1 ? ` and ${o.seen.length - 1} more time${o.seen.length > 2 ? 's' : ''}` : ''}{differs ? ` · detector said “${o.yoloe}”` : ''}</div>
        {o.hidden && <div className="type-caption italic text-muted-foreground">{WHY[o.hidden]}</div>}
      </div>
      <Button size="sm" className="flex-none" aria-label={`Look at ${name}`} onClick={() => onLook({ lon: o.lon, lat: o.lat, fov: framing(o.deg), t: o.best_t })}>Look</Button>
      {onHide && <div className="flex flex-none flex-col items-stretch gap-0.5 type-caption">
        {!o.hidden && <><Tooltip label="Hide this one (the data is kept)"><Button size="sm" aria-label={`Hide ${name}`} onClick={() => onHide(o, 'object', true)}>Hide</Button></Tooltip>
          <Tooltip label="Hide every thing with this name, in every clip"><Button size="sm" aria-label={`Hide every ${name}`} onClick={() => onHide(o, 'label', true)}>Hide all</Button></Tooltip></>}
        {(o.hidden === 'object' || o.hidden === 'label') && <Button size="sm" aria-label={`Show ${name} again`} onClick={() => onHide(o, o.hidden === 'label' ? 'label' : 'object', false)}>Show again</Button>}
      </div>}
    </li>
  )
}

const AreaRow = ({ r, onLook }: { r: Region; onLook: (l: Look) => void }) => (
  <li className="flex items-center gap-3 py-1 type-body-sm">
    <span className={`h-3 w-3 flex-none rounded-control ${r.kind === 'snow' ? 'border border-border bg-card' : 'bg-info'}`} aria-hidden="true" />
    <span className="flex-1">{r.kind === 'snow' ? 'Snow' : 'Water'} <span className="type-caption text-muted-foreground">{where(r.lon, r.lat)} · {Math.round(r.w_deg)}° × {Math.round(r.h_deg)}° · in view {fmt(r.seen[0] ?? 0)}{r.seen.length > 1 ? ` and ${r.seen.length - 1} more` : ''}</span></span>
    <Button size="sm" aria-label={`Look at ${r.kind} at ${where(r.lon, r.lat)}`} onClick={() => onLook({ lon: r.lon, lat: r.lat, fov: framingArea(r.w_deg, r.h_deg), t: r.seen[0] ?? 0 })}>Look</Button>
  </li>
)

/** What the objects stage found in a clip: the things passed (a picture, the name, where and when) and the areas of snow and water, each with a button that turns the player to it, and a switch for marking them on the video. */
export default function ObjectsCard({ folder, clip, info, marked, onMarked, onLook, onHide }: { folder: string; clip: string; info: ObjectsInfo | null | undefined; marked: boolean; onMarked: (on: boolean) => void; onLook: (l: Look) => void; onHide?: Hide }) {
  const [all, setAll] = useState(false), [showHidden, setShowHidden] = useState(false)
  if (!info) return <p className="type-body-sm text-muted-foreground">The objects stage has not run for this clip yet.</p>
  if (info.skipped) return <p className="type-body-sm text-muted-foreground">Not looked at: {info.skipped}.</p>
  const nHidden = info.objects.filter(o => o.hidden).length, list = [...info.objects].filter(o => showHidden || !o.hidden).sort((a, b) => (a.seen[0] ?? a.best_t) - (b.seen[0] ?? b.best_t)), shown = all ? list : list.slice(0, LIMIT)
  const areas = [...info.regions].sort((a, b) => a.kind.localeCompare(b.kind) || b.w_deg * b.h_deg - a.w_deg * a.h_deg)
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 type-caption text-muted-foreground">
        <span>{list.length - (showHidden ? nHidden : 0)} thing{list.length - (showHidden ? nHidden : 0) === 1 ? '' : 's'}{areas.length ? `, ${areas.length} area${areas.length === 1 ? '' : 's'} of snow or water` : ''}, from {info.moments} moments{info.model ? ` · named by ${info.model}` : ''}</span>
        <span className="flex flex-wrap items-center gap-3">
          {nHidden > 0 && <Checkbox label={`Show ${nHidden} hidden`} checked={showHidden} onCheckedChange={(checked: boolean) => setShowHidden(checked)} />}
          <Checkbox label="Show on the video" checked={marked} onCheckedChange={(checked: boolean) => onMarked(checked)} />
        </span>
      </div>
      {list.length === 0 && areas.length === 0 && <p className="type-body-sm text-muted-foreground">Nothing found.</p>}
      <ul className="divide-y divide-border">{shown.map(o => <Row key={o.id} o={o} folder={folder} clip={clip} onLook={onLook} onHide={onHide} />)}</ul>
      {list.length > LIMIT && <Button variant="link" size="sm" className="mt-1" onClick={() => setAll(a => !a)}>{all ? 'show fewer' : `show all ${list.length}`}</Button>}
      {areas.length > 0 && <><h4 className="mb-1 mt-3 type-caption font-semibold uppercase tracking-wide text-muted-foreground">Snow and water</h4><ul>{areas.map((r, i) => <AreaRow key={i} r={r} onLook={onLook} />)}</ul></>}
      {Object.keys(info.scenery_labels).length > 0 && <p className="mt-2 type-caption text-muted-foreground">Scenery not listed: {Object.entries(info.scenery_labels).map(([k, n]) => `${k} (${n})`).join(', ')}</p>}
    </div>
  )
}
