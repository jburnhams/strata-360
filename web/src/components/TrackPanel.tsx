import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type TileStatus, type TrackClip, type TrackLine, type TrackOverview, type TrackSeries } from '../api'
import { useThumbOverlay } from '../thumbOverlay'
import { PanelSkeleton } from './Skeleton'
import TrackMap from './TrackMap'
import TrackCharts, { type XMode } from './TrackCharts'
import ClipCard from './ClipCard'
import GapsPanel from './GapsPanel'

// The race track (Garmin FIT or GPX) saved in the project as track.fit / track.gpx: the main numbers, a zoomable map with a marker for every clip, and elevation and pace charts with the same markers; or an upload box.
// Hover a marker for the clip's card, click it to open the clip.
export default function TrackPanel({ folder, onOpenClip = () => {}, tz = 'Europe/Brussels' }: { folder: string; onOpenClip?: (clip: string) => void; tz?: string }) {
  const [t, setT] = useState<TrackOverview>()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { api.track(folder).then(setT).catch(e => setErr(e.message)) }, [folder])

  const upload = async (f?: File) => {
    if (!f) return
    setBusy(true); setErr(undefined)
    try { setT(await api.uploadTrack(folder, f)) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const pick = <input ref={input} type="file" accept=".fit,.gpx" hidden onChange={e => upload(e.target.files?.[0])} />

  if (!t) return err ? <p className="mt-4 text-sm text-red-600">{err}</p> : <PanelSkeleton title="Race track" rows={4} />
  if (!t.present || t.error) {
    return (
      <div className="mt-4 rounded-xl border border-dashed border-stone-300 p-6 text-center dark:border-stone-700"
        onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); upload(e.dataTransfer.files[0]) }}>
        {pick}
        <p className="mb-2">{t.error ? `Could not read the track: ${t.error}` : 'No race track yet.'}</p>
        <p className="mb-3 text-sm text-stone-500">Add the Garmin .fit or a .gpx file. It gives the map, pace and climb for every clip, and checks the camera clock.</p>
        <button disabled={busy} className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-50" onClick={() => input.current?.click()}>{busy ? 'Reading…' : 'Choose a file'}</button>
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      </div>
    )
  }
  const stat = (label: string, v: string | number | null | undefined, unit = '') => v == null ? null : (
    <div><div className="text-xs text-stone-500">{label}</div><div className="text-lg font-medium">{v}<span className="text-sm text-stone-500"> {unit}</span></div></div>
  )
  const pace = t.avg_pace_min_km ? `${Math.floor(t.avg_pace_min_km)}:${String(Math.round((t.avg_pace_min_km % 1) * 60)).padStart(2, '0')}` : null
  return (
    <div className="mt-4 rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      {pick}
      <div className="mb-3 flex items-center justify-between">
        <div><b>Race track</b> <span className="text-sm text-stone-500">{t.file} · {t.start_utc?.slice(0, 10)} → {t.end_utc?.slice(0, 10)} UTC</span></div>
        <button disabled={busy} className="text-sm text-emerald-700 underline dark:text-emerald-400" onClick={() => input.current?.click()}>{busy ? 'Reading…' : 'Replace'}</button>
      </div>
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-9">
        {stat('Distance', t.distance_km, 'km')}{stat('Duration', t.duration_h, 'h')}{stat('Moving', t.moving_h, 'h')}
        {stat('Climb', t.ascent_m?.toLocaleString(), 'm')}{stat('Descent', t.descent_m?.toLocaleString(), 'm')}{stat('Avg pace', pace, 'min/km')}
        {stat('Altitude', t.min_altitude_m != null ? `${t.min_altitude_m}–${t.max_altitude_m}` : null, 'm')}{stat('Heart rate', t.avg_hr != null ? `${t.avg_hr} (max ${t.max_hr})` : null)}{stat('Points', t.samples?.toLocaleString())}
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <RaceView folder={folder} onOpenClip={onOpenClip} tz={tz} />
      <GapsPanel folder={folder} />
    </div>
  )
}

function RaceView({ folder, onOpenClip, tz }: { folder: string; onOpenClip: (clip: string) => void; tz: string }) {
  const [overlay] = useThumbOverlay()
  const [base, setBase] = useState<TrackLine>(), [series, setSeries] = useState<TrackSeries>(), [clips, setClips] = useState<TrackClip[]>([]), [hasDraft, setHasDraft] = useState(false), [tiles, setTiles] = useState<TileStatus>(), [err, setErr] = useState<string>()
  const [xMode, setXMode] = useState<XMode>('time'), [cursor, setCursor] = useState<number | null>(null), [hover, setHover] = useState<{ clip: TrackClip; x: number; y: number }>()
  useEffect(() => {
    setErr(undefined); setBase(undefined); setSeries(undefined)
    api.tilesStatus().then(setTiles).catch(e => setTiles({ ok: false, style: 'tf-landscape', error: (e as Error).message }))
    Promise.all([api.trackLine(folder, undefined, 4000), api.trackSeries(folder, 2000), api.trackClips(folder)])
      .then(([b, s, c]) => { setBase(b); setSeries(s); setClips(c.clips); setHasDraft(c.has_draft) }).catch(e => setErr((e as Error).message))
  }, [folder])
  const hoverClip = (c: TrackClip | null, x = 0, y = 0) => setHover(c ? { clip: c, x, y } : undefined)
  const off = useMemo(() => clips.filter(c => !c.covered), [clips])
  if (err) return <p className="mt-3 text-sm text-amber-700">The map and charts need the track and its clips: {err}</p>
  if (!base || !series) return <div className="mt-3 h-[420px] animate-pulse rounded-lg bg-stone-100 dark:bg-stone-800" aria-label="Loading the race map" />
  return (
    <div className="mt-3 space-y-2">
      {tiles && !tiles.ok && <p role="alert" className="text-sm text-amber-700">The map background is off: {tiles.error}</p>}
      <TrackMap background={tiles?.ok ? { url: api.tileUrl(tiles.style), tilePx: tiles.tile_px ?? 256 } : undefined} base={base} clips={clips} cursor={cursor} onCursor={setCursor} onHoverClip={hoverClip} onOpenClip={onOpenClip} fetchDetail={bbox => api.trackLine(folder, bbox, 4000)} />
      <div className="flex flex-wrap items-center gap-3 text-xs text-stone-500">
        <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: '#16a34a' }} />{hasDraft ? 'played by the newest script draft' : 'clip'}</span>
        {hasDraft && <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: '#78716c' }} />not in the film</span>}
        <span>click the map, then scroll to zoom</span>
        {tiles?.ok && tiles.credit && <span>{tiles.credit}</span>}
        <span>{clips.filter(c => c.covered).length} clips on the track{off.length ? ` · not on the track: ${off.map(c => c.label).join(', ')}` : ''}</span>
        <span className="ml-auto flex items-center gap-1">horizontal axis
          <select aria-label="Horizontal axis" value={xMode} onChange={e => setXMode(e.target.value as XMode)} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700"><option value="time">time</option><option value="km">distance</option></select></span>
      </div>
      <TrackCharts series={series} clips={clips} xMode={xMode} tz={tz} cursor={cursor} onCursor={setCursor} onHoverClip={hoverClip} onOpenClip={onOpenClip} />
      {hover && <div className="pointer-events-none fixed z-40" style={{ left: Math.min(hover.x + 16, window.innerWidth - 280), top: Math.min(hover.y + 16, window.innerHeight - 330) }}><ClipCard folder={folder} clip={hover.clip} overlay={overlay} /></div>}
    </div>
  )
}
