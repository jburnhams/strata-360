import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { api, type ExtraLine, type TileStatus, type TrackKind, type TracksListing, type TrackClip, type TrackLine, type TrackOverview, type TrackSeries } from '../api'
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
  const [listing, setListing] = useState<TracksListing>(), [ver, setVer] = useState(0)
  const [hot, setHot] = useState<string | null>(null), [pinned, setPinned] = useState<string[]>([])                  // the track pointed at, and the tracks picked (click again to let go): shown in bold yellow on the map and in the list
  const toggle = (id: string) => setPinned(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id])
  useEffect(() => { api.track(folder).then(setT).catch(e => setErr(e.message)); api.tracks(folder).then(setListing).catch(() => {}) }, [folder])
  const changed = async () => { try { const [o, l] = await Promise.all([api.track(folder), api.tracks(folder)]); setT(o); setListing(l); setVer(v => v + 1) } catch (e) { setErr((e as Error).message) } }   // the race track follows the runs

  const upload = async (f?: File) => {
    if (!f) return
    setBusy(true); setErr(undefined)
    try { setT(await api.uploadTrack(folder, f)); api.tracks(folder).then(setListing).catch(() => {}); setVer(v => v + 1) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
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
      <TracksList folder={folder} listing={listing} onChange={changed} tz={tz} hot={hot} setHot={setHot} pinned={pinned} toggle={toggle} />
      <RaceView key={ver} folder={folder} listing={listing} onOpenClip={onOpenClip} tz={tz} hot={hot} setHot={setHot} pinned={pinned} toggle={toggle} />
      <GapsPanel folder={folder} />
    </div>
  )
}

type Pick = { hot: string | null; setHot: (id: string | null) => void; pinned: string[]; toggle: (id: string) => void }
function RaceView({ folder, listing, onOpenClip, tz, hot, setHot, pinned, toggle }: { folder: string; listing?: TracksListing; onOpenClip: (clip: string) => void; tz: string } & Pick) {
  const [overlay] = useThumbOverlay()
  const [base, setBase] = useState<TrackLine>(), [series, setSeries] = useState<TrackSeries>(), [clips, setClips] = useState<TrackClip[]>([]), [hasDraft, setHasDraft] = useState(false), [tiles, setTiles] = useState<TileStatus>(), [err, setErr] = useState<string>()
  const [xMode, setXMode] = useState<XMode>('time'), [cursor, setCursor] = useState<number | null>(null), [hover, setHover] = useState<{ clip: TrackClip; x: number; y: number }>()
  useEffect(() => {
    setErr(undefined); setBase(undefined); setSeries(undefined)
    api.tilesStatus().then(setTiles).catch(e => setTiles({ ok: false, style: 'tf-landscape', error: (e as Error).message }))
    Promise.all([api.trackLine(folder, undefined, 4000), api.trackSeries(folder, 2000), api.trackClips(folder)])
      .then(([b, s, c]) => { setBase(b); setSeries(s); setClips(c.clips); setHasDraft(c.has_draft) }).catch(e => setErr((e as Error).message))
  }, [folder])
  const [extras, setExtras] = useState<ExtraLine[]>([])
  useEffect(() => {                                                                                  // every route, and every run when there are several (the race track above them is the merged one)
    if (!listing) { setExtras([]); return }
    const want = listing.tracks.filter(x => !x.error && (x.kind === 'route' || listing.runs > 1))
    let live = true
    Promise.all(want.map(x => api.tracksLine(folder, x.id).then(l => ({ id: x.id, kind: x.kind, name: x.name, lat: l.lat, lon: l.lon }) as ExtraLine).catch(() => null)))
      .then(r => { if (live) setExtras(r.filter((x): x is ExtraLine => !!x)) })
    return () => { live = false }
  }, [folder, listing])
  const [lines, setLines] = useState<Record<string, ExtraLine>>({})                                  // the line of every track that has been highlighted (fetched when first needed)
  const ids = useMemo(() => Array.from(new Set([...pinned, ...(hot ? [hot] : [])])), [pinned, hot])
  useEffect(() => {
    for (const id of ids) {
      if (lines[id] || extras.some(e => e.id === id)) continue
      if (id.startsWith('cp:')) continue
      const t = listing?.tracks.find(x => x.id === id); if (!t) continue
      api.tracksLine(folder, id).then(l => setLines(c => ({ ...c, [id]: { id, kind: t.kind, name: t.name, lat: l.lat, lon: l.lon } }))).catch(() => {})
    }
  }, [ids, lines, extras, listing, folder])
  const highlight = useMemo(() => ids.map(id => extras.find(e => e.id === id) ?? lines[id]).filter((x): x is ExtraLine => !!x), [ids, extras, lines])
  const cps = useMemo(() => ids.filter(id => id.startsWith('cp:')).map(id => Number(id.slice(3))), [ids])                    // checkpoints pointed at or picked in the list: ringed in yellow on the map
  const hoverClip = (c: TrackClip | null, x = 0, y = 0) => setHover(c ? { clip: c, x, y } : undefined)
  const off = useMemo(() => clips.filter(c => !c.covered), [clips])
  if (err) return <p className="mt-3 text-sm text-amber-700">The map and charts need the track and its clips: {err}</p>
  if (!base || !series) return <div className="mt-3 h-[420px] animate-pulse rounded-lg bg-stone-100 dark:bg-stone-800" aria-label="Loading the race map" />
  return (
    <div className="mt-3 space-y-2">
      {tiles && !tiles.ok && <p role="alert" className="text-sm text-amber-700">The map background is off: {tiles.error}</p>}
      <TrackMap background={tiles?.ok ? { url: api.tileUrl(tiles.style), tilePx: tiles.tile_px ?? 256 } : undefined} base={base} clips={clips} cursor={cursor} onCursor={setCursor} onHoverClip={hoverClip} onOpenClip={onOpenClip} fetchDetail={bbox => api.trackLine(folder, bbox, 4000)} extras={extras} pois={listing?.pois ?? []} divergences={listing?.divergences ?? []} highlight={highlight} onHoverTrack={setHot} onToggleTrack={toggle} tz={tz} ends={listing?.markers} highlightCheckpoints={cps} ringEnds={ids.includes('finish')} />
      <div className="flex flex-wrap items-center gap-3 text-xs text-stone-500">
        <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: '#16a34a' }} />{hasDraft ? 'played by the newest script draft' : 'clip'}</span>
        {hasDraft && <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: '#78716c' }} />not in the film</span>}
        {extras.some(e => e.kind === 'route') && <span><span className="mr-1 inline-block h-0 w-4 border-t-2 border-dashed align-middle" style={{ borderColor: '#2563eb' }} />route (planning only)</span>}
        {(listing?.runs ?? 0) > 1 && <span><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: '#a3a3a3' }} />each run · <span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: '#15803d' }} />merged race track</span>}
        {(listing?.divergences?.length ?? 0) > 0 && <span><span className="mr-1 inline-block h-3.5 w-3.5 rounded-full bg-red-600 text-center align-middle text-[10px] font-bold leading-[14px] text-white">!</span>run leaves the route by over 50 m (the {listing?.divergences?.length} farthest)</span>}
        {(listing?.pois.some(p => p.sym === 'checkpoint')) && <span><span className="mr-1 inline-block h-3.5 w-3.5 rounded-full bg-blue-700 text-center align-middle text-[9px] font-bold leading-[14px] text-white">1</span>checkpoint where one route ends and the next starts</span>}
        {(listing?.pois.length ?? 0) > 0 && <span><span className="mr-1 inline-block h-2.5 w-2.5 rotate-45 align-middle" style={{ background: '#f59e0b' }} />point of interest</span>}
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

// The project's tracks: every uploaded FIT / GPX file marked a run (merged into the one race track) or a route (the course, shown on the map for planning only).
const pace = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
const stamp = (t: number, tz: string) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)).replace(',', '') } catch { return new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' ') } }
const hms = (s: number) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(Math.round(s % 60)).padStart(2, '0')}`
function TracksList({ folder, listing, onChange, hot, setHot, pinned, toggle, tz }: { folder: string; listing?: TracksListing; onChange: () => Promise<void>; tz: string } & Pick) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string>(), input = useRef<HTMLInputElement>(null)
  const act = async (f: () => Promise<unknown>) => { setBusy(true); setErr(undefined); try { await f() } catch (e) { setErr((e as Error).message) } finally { try { await onChange() } finally { setBusy(false) } } }
  const add = (files: FileList | File[] | null) => act(async () => { for (const f of Array.from(files ?? [])) await api.addTrack(folder, f) })
  const rows = listing?.tracks ?? [], tm = listing?.timing, lastRun = rows.reduce((a, r, i) => (r.kind === 'run' ? i : a), -1)
  const cpTime = tm ? Object.values(tm.checkpoints).reduce((a, b) => a + b, 0) : 0, runTime = tm ? tm.total_s - cpTime : 0, ranKm = tm?.ran_m ? Object.values(tm.ran_m).reduce((a, b) => a + b, 0) / 1000 : 0
  return (
    <div className="mt-3 rounded-lg border border-stone-200 p-3 text-sm dark:border-stone-800" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files) }}>
      <input ref={input} type="file" accept=".fit,.gpx" multiple hidden aria-label="Add track files" onChange={e => { add(e.target.files); e.target.value = '' }} />
      <div className="flex items-center justify-between">
        <b>Tracks</b>
        <button disabled={busy} className="text-emerald-700 underline disabled:opacity-50 dark:text-emerald-400" onClick={() => input.current?.click()}>{busy ? 'Working…' : 'Add tracks'}</button>
      </div>
      <p className="mb-2 text-xs text-stone-500">Mark each file a run (the recording; several runs are merged into the race track) or a route (a planned or official course, shown on the map for planning only).</p>
      {rows.length === 0 && <p className="text-stone-500">No tracks listed.</p>}
      <ul className="space-y-1">
        {rows.map((x, ix) => (<Fragment key={x.id}>
          <li data-highlighted={hot === x.id || pinned.includes(x.id) ? '' : undefined} onMouseEnter={() => setHot(x.id)} onMouseLeave={() => setHot(null)}
            className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded px-1 ${hot === x.id || pinned.includes(x.id) ? 'bg-yellow-200 font-semibold text-black ring-1 ring-black dark:bg-yellow-300' : ''}`}>
            {x.kind === 'route' && <span className="w-6 text-center text-xs font-semibold text-blue-700 dark:text-blue-400" title={x.order ? `section ${x.order} of the race` : undefined}>{x.order ?? ''}</span>}
            <button type="button" aria-pressed={pinned.includes(x.id)} aria-label={`Highlight ${x.name} on the map`} className="min-w-0 flex-1 cursor-pointer truncate text-left" title={`${x.name} (click to keep it highlighted on the map)`} onClick={() => toggle(x.id)}>{x.name}</button>
            {x.error ? <span className="text-red-600">{x.error}</span> : <span className="text-xs text-stone-500">{x.distance_km} km{x.start_utc ? ` · ${x.start_utc.slice(0, 10)}` : ''}{x.pois ? ` · ${x.pois} POI` : ''}</span>}
            {x.time_s != null && <span className="text-sm tabular-nums" title="time on this route, from leaving the previous checkpoint to arriving at the next (the checkpoints' own time is not in it)">{hms(x.time_s)}{x.ran_km != null ? <span className="text-xs text-stone-500"> · {x.ran_km} km run{x.pace_s_km ? ` · ${pace(x.pace_s_km)} /km` : ''}{x.ascent_m != null ? ` · ↑${x.ascent_m} m ↓${x.descent_m} m` : ''}</span> : null}</span>}
            <select aria-label={`Kind of ${x.name}`} value={x.kind} disabled={busy} onChange={e => act(() => api.setTrackKind(folder, x.id, e.target.value as TrackKind))} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
              <option value="run">run</option><option value="route">route</option>
            </select>
            <button disabled={busy} aria-label={`Remove ${x.name}`} className="text-stone-500 hover:text-red-600 disabled:opacity-50" onClick={() => act(() => api.removeTrack(folder, x.id))}>Remove</button>
          </li>
          {x.order != null && listing?.timing?.checkpoints[String(x.order)] != null && (
            <li data-checkpoint-row="" data-highlighted={hot === `cp:${x.order}` || pinned.includes(`cp:${x.order}`) ? '' : undefined} onMouseEnter={() => setHot(`cp:${x.order}`)} onMouseLeave={() => setHot(null)}
              className={`flex items-center gap-x-3 rounded px-1 text-xs ${hot === `cp:${x.order}` || pinned.includes(`cp:${x.order}`) ? 'bg-yellow-200 font-semibold text-black ring-1 ring-black dark:bg-yellow-300' : 'text-blue-800 dark:text-blue-300'}`}>
              <span className="w-6 text-center"><span className="inline-block h-4 min-w-4 rounded-full bg-blue-700 px-1 text-center text-[10px] font-bold leading-4 text-white">{x.order}</span></span>
              <button type="button" aria-pressed={pinned.includes(`cp:${x.order}`)} aria-label={`Highlight checkpoint ${x.order} on the map`} className="flex-1 cursor-pointer text-left" onClick={() => toggle(`cp:${x.order}`)}>Checkpoint {x.order}{listing.timing.arrivals?.[String(x.order)] && <span className="ml-3 text-stone-500" title="where the run was when it arrived: distance and time since the start, and when">km {listing.timing.arrivals[String(x.order)].km} · {hms(listing.timing.arrivals[String(x.order)].elapsed_s)} since start · arrived {stamp(listing.timing.arrivals[String(x.order)].t, tz)}</span>}</button><span className="text-sm tabular-nums">{hms(listing.timing.checkpoints[String(x.order)])}</span>
            </li>
          )}
          {tm && x.kind === 'run' && ix === lastRun && (
            <li data-timing="" className="rounded bg-stone-100 px-2 py-1 text-sm dark:bg-stone-800">
              <div className="flex flex-wrap gap-x-5 gap-y-1 tabular-nums">
                <span title="first to last point of the run">Total time <b>{hms(tm.total_s)}</b></span>
                <span title="time at the checkpoints, from the first slow arrival to the last slow leaving">Checkpoints <b>{hms(cpTime)}</b></span>
                <span title="total time without the checkpoints">Running time <b>{hms(runTime)}</b></span>
                {ranKm > 0 && <span title="the distance actually run over the running time">Running pace <b>{pace(runTime / ranKm)}</b> /km <span className="text-xs text-stone-500">({ranKm.toFixed(1)} km)</span></span>}
                {tm.ascent_m != null && <span>Ascent <b>{tm.ascent_m.toLocaleString()} m</b></span>}{tm.descent_m != null && <span>Descent <b>{tm.descent_m.toLocaleString()} m</b></span>}
              </div>
              {!tm.consistent && <div className="text-xs text-red-600">The checkpoints do not come in order along the run: check them.</div>}
            </li>
          )}
        </Fragment>))}
        {listing?.finish && rows.some(r => r.order != null) && (
          <li data-finish-row="" data-highlighted={hot === 'finish' || pinned.includes('finish') ? '' : undefined} onMouseEnter={() => setHot('finish')} onMouseLeave={() => setHot(null)}
            className={`flex items-center gap-x-3 rounded px-1 text-xs ${hot === 'finish' || pinned.includes('finish') ? 'bg-yellow-200 font-semibold text-black ring-1 ring-black dark:bg-yellow-300' : 'text-stone-700 dark:text-stone-300'}`}>
            <span className="w-6 text-center"><span className="inline-block h-4 w-4 rounded-full align-middle" style={{ background: 'conic-gradient(#000 25%, #fff 0 50%, #000 0 75%, #fff 0)', border: '1.5px solid #78716c' }} /></span>
            <button type="button" aria-pressed={pinned.includes('finish')} aria-label="Highlight the finish on the map" className="flex-1 cursor-pointer text-left" onClick={() => toggle('finish')}>
              Finish{listing.finish.reached ? '' : ' (not reached)'}
              <span className="ml-3 opacity-80" title="the finish line of the routes">{listing.finish.reached && listing.finish.km != null ? `km ${listing.finish.km} · ${hms(listing.finish.elapsed_s ?? 0)} since start · arrived ${stamp(listing.finish.t ?? 0, tz)} · ` : ''}routes {(listing.finish.route_m / 1000).toFixed(1)} km{listing.finish.reached ? '' : `, covered ${(listing.finish.covered_m / 1000).toFixed(1)} km`}</span></button>
            {listing.finish.time_s != null && <span className="text-sm tabular-nums" title="time at the finish, to the end of the run">{hms(listing.finish.time_s)}</span>}
          </li>
        )}
      </ul>
      {listing?.merged && <p className="mt-2 text-xs text-stone-500">Race track = {listing.merged.runs.length} runs merged · {listing.merged.distance_km} km · {listing.merged.samples.toLocaleString()} points</p>}
      {err && <p role="alert" className="mt-2 text-red-600">{err}</p>}
    </div>
  )
}
