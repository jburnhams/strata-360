import { api, type TrackClip } from '../api'
import { fmtElapsed, fmtPace } from '../trackMath'

// What a clip's marker shows on hover: its picture and the facts about where in the race it is, and whether the newest script draft plays it.
export default function ClipCard({ folder, clip, overlay }: { folder: string; clip: TrackClip; overlay: boolean }) {
  const f = clip.facts
  const row = (k: string, v: React.ReactNode) => v == null || v === '' ? null : <div className="flex justify-between gap-3"><span className="text-stone-500">{k}</span><span>{v}</span></div>
  return (
    <div className="w-64 overflow-hidden rounded-lg border border-stone-300 bg-white text-xs shadow-lg dark:border-stone-700 dark:bg-stone-900" role="tooltip">
      <img src={api.thumbUrl(folder, clip.id, '0', overlay)} alt="" className="aspect-video w-full bg-stone-200 object-cover dark:bg-stone-800" onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }} />
      <div className="space-y-0.5 p-2">
        <div className="flex items-center justify-between font-mono text-stone-500"><span>clip {clip.label}</span><span className={`rounded-full px-2 ${clip.used ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-stone-200 text-stone-600 dark:bg-stone-800 dark:text-stone-400'}`}>{clip.used ? `in the film · ${clip.used_s} s` : 'not in the film'}</span></div>
        {f && <div className="text-sm">{f.local}{f.daylight ? <span className="text-stone-500"> · {f.daylight}</span> : null}</div>}
        {row('length', clip.duration_s >= 60 ? fmtElapsed(clip.duration_s) : `${Math.round(clip.duration_s)} s`)}
        {f && row('distance', f.distance_km != null ? `km ${f.distance_km}${f.percent != null ? ` (${Math.round(f.percent)}%)` : ''}` : null)}
        {f && row('pace', f.pace_min_km != null ? `${fmtPace(f.pace_min_km)} /km` : 'stopped or very slow')}
        {f && row('gradient', f.gradient_pct != null ? `${f.gradient_pct > 0 ? '+' : ''}${Math.round(f.gradient_pct)}%` : null)}
        {f && row('altitude', f.altitude_m != null ? `${Math.round(f.altitude_m)} m` : null)}
        {f && row('heart rate', f.heart_rate)}
        {clip.scene && row('camera sees', [...clip.scene.settings, ...clip.scene.weather].join(', '))}
        {row('usable moments', clip.moments)}
        <div className="pt-1 text-emerald-700 dark:text-emerald-400">click to open this clip</div>
      </div>
    </div>
  )
}
