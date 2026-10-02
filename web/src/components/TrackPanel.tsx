import { useEffect, useRef, useState } from 'react'
import { api, type TrackOverview } from '../api'
import { PanelSkeleton } from './Skeleton'

// The race track (Garmin FIT or GPX) saved in the project as track.fit / track.gpx: an offline overview map and the main numbers, or an upload box; click to replace.
export default function TrackPanel({ folder }: { folder: string }) {
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
    <div className="mt-4 grid gap-4 rounded-xl border border-stone-200 bg-white p-4 md:grid-cols-[1fr_280px] dark:border-stone-800 dark:bg-stone-900">
      {pick}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <div><b>Race track</b> <span className="text-sm text-stone-500">{t.file} · {t.start_utc?.slice(0, 10)} → {t.end_utc?.slice(0, 10)} UTC</span></div>
          <button disabled={busy} className="text-sm text-emerald-700 underline dark:text-emerald-400" onClick={() => input.current?.click()}>{busy ? 'Reading…' : 'Replace'}</button>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {stat('Distance', t.distance_km, 'km')}{stat('Duration', t.duration_h, 'h')}{stat('Moving', t.moving_h, 'h')}
          {stat('Climb', t.ascent_m?.toLocaleString(), 'm')}{stat('Descent', t.descent_m?.toLocaleString(), 'm')}{stat('Avg pace', pace, 'min/km')}
          {stat('Altitude', t.min_altitude_m != null ? `${t.min_altitude_m}–${t.max_altitude_m}` : null, 'm')}{stat('Heart rate', t.avg_hr != null ? `${t.avg_hr} (max ${t.max_hr})` : null)}{stat('Points', t.samples?.toLocaleString())}
        </div>
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      </div>
      <Map t={t} />
    </div>
  )
}

// Offline map: the polyline in an equirectangular projection scaled by cos(latitude); start (green) and finish (red) marked.
function Map({ t }: { t: TrackOverview }) {
  if (!t.line?.length || !t.bbox) return null
  const [la0, lo0, la1, lo1] = t.bbox, k = Math.cos(((la0 + la1) / 2) * Math.PI / 180)
  const w = (lo1 - lo0) * k || 1e-6, h = (la1 - la0) || 1e-6, S = 260 / Math.max(w, h), pad = 10
  const pt = ([la, lo]: [number, number]) => [pad + (lo - lo0) * k * S, pad + (la1 - la) * S] as const
  const pts = t.line.map(pt), d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('')
  const W = w * S + 2 * pad, H = h * S + 2 * pad
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg bg-stone-100 dark:bg-stone-950" role="img" aria-label="Track overview">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" className="text-emerald-700 dark:text-emerald-400" />
      <circle cx={pts[0][0]} cy={pts[0][1]} r="4" fill="#16a34a" /><circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="4" fill="#dc2626" />
    </svg>
  )
}
