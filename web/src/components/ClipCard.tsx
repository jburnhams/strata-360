import { api, type TrackClip } from '../api'
import { fmtElapsed, fmtPace } from '../trackMath'

// What a clip's marker shows on hover: its picture and the facts about where in the race it is, and whether the newest script draft plays it.
export default function ClipCard({ folder, clip, overlay }: { folder: string; clip: TrackClip; overlay: boolean }) {
  const f = clip.facts
  const row = (k: string, v: React.ReactNode) => v == null || v === '' ? null : <div className="flex justify-between gap-3"><span className="text-muted-foreground">{k}</span><span>{v}</span></div>
  return (
    <div className="w-64 overflow-hidden rounded-surface border border-border bg-card type-caption shadow-overlay" role="tooltip">
      <img src={api.thumbUrl(folder, clip.id, '0', overlay)} alt="" className="aspect-video w-full bg-muted object-cover" onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }} />
      <div className="space-y-0.5 p-2">
        <div className="flex items-center justify-between font-mono text-muted-foreground"><span>clip {clip.label}</span><span className={`rounded-pill px-2 ${clip.used ? 'bg-primary-3 text-primary' : 'bg-muted text-muted-foreground'}`}>{clip.used ? `in the film · ${clip.used_s} s` : 'not in the film'}</span></div>
        {f && <div className="type-body-sm">{f.local}{f.daylight ? <span className="text-muted-foreground"> · {f.daylight}</span> : null}</div>}
        {row('length', clip.duration_s >= 60 ? fmtElapsed(clip.duration_s) : `${Math.round(clip.duration_s)} s`)}
        {f && row('distance', f.distance_km != null ? `km ${f.distance_km}${f.percent != null ? ` (${Math.round(f.percent)}%)` : ''}` : null)}
        {f && row('pace', f.pace_min_km != null ? `${fmtPace(f.pace_min_km)} /km` : 'stopped or very slow')}
        {f && row('gradient', f.gradient_pct != null ? `${f.gradient_pct > 0 ? '+' : ''}${Math.round(f.gradient_pct)}%` : null)}
        {f && row('altitude', f.altitude_m != null ? `${Math.round(f.altitude_m)} m` : null)}
        {f && row('heart rate', f.heart_rate)}
        {clip.scene && row('camera sees', [...clip.scene.settings, ...clip.scene.weather].join(', '))}
        {row('usable moments', clip.moments)}
        <div className="pt-1 text-primary">click to open this clip</div>
      </div>
    </div>
  )
}
