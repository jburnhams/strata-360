import { useState } from 'react'
import { api, type EnlargeMode } from '../api'
import { ENLARGE } from './stillModes'
import { usePoll } from '../usePoll'
import RenderProgress from './RenderProgress'
import OverlaySettings from './OverlaySettings'
import { Button, Checkbox } from 'strata-react'

const eta = (st: { frames_done?: number; frames_total?: number; started?: number }) => {
  if (!st.frames_done || !st.frames_total || !st.started) return ''
  const secs = (Date.now() / 1000 - st.started) * (st.frames_total - st.frames_done) / st.frames_done
  return secs > 90 ? ` · about ${Math.round(secs / 60)} min left` : ''
}

// The final film: rendered from the original video at full quality (slow, at the lowest priority, resumable: pieces that are finished are kept if you stop it or the plan is unchanged).
export default function FinalRender({ folder }: { folder: string }) {
  const st = usePoll(() => api.final(folder), 3000, [folder])
  const [size, setSize] = useState<string>(), [fps, setFps] = useState<number>(), [half, setHalf] = useState<boolean>(), [up, setUp] = useState<EnlargeMode>()
  if (!st || st.state === 'noplan') return null
  const busy = st.state === 'starting' || st.state === 'rendering' || st.state === 'assembling'
  const pct = st.frames_total ? Math.round(100 * (st.frames_done ?? 0) / st.frames_total) : 0
  const sel = 'rounded-surface border border-border bg-card px-2 py-1 type-body-sm'
  return (
    <section className="rounded-overlay border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="type-body-sm font-semibold">Final film</h3>
        {!busy && <>
          <label className="type-body-sm">Size <select className={sel} value={size ?? st.settings.size} onChange={e => setSize(e.target.value)}><option value="1920x1080">1080p</option><option value="2560x1440">1440p</option><option value="3840x2160">4K</option></select></label>
          <label className="type-body-sm">Frames/s <select className={sel} value={fps ?? st.settings.fps} onChange={e => setFps(Number(e.target.value))}><option value={0}>the footage's own</option><option value={25}>25</option><option value={30}>30</option><option value={50}>50</option></select></label>
          <Checkbox label="Half frame rate (faster)" checked={half ?? st.settings.half_rate} onCheckedChange={(checked: boolean) => setHalf(checked)} />
          <label className="type-body-sm" title="Runs the local upscaling model on shots that hold too few pixels for the size (tight zooms; not night footage). Slow: at 4K nearly every shot qualifies, so 1080p or 1440p then a resample is much cheaper.">Enlarge <select className={sel} value={up ?? st.settings.upscale} onChange={e => setUp(e.target.value as EnlargeMode)}>{ENLARGE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <Button variant="default" onClick={() => api.startFinal(folder, { size: size ?? st.settings.size, fps: fps ?? st.settings.fps, half_rate: half ?? st.settings.half_rate, upscale: up ?? st.settings.upscale })}>{st.state === 'done' ? 'Render again' : st.state === 'stopped' || (st.pieces_done ?? 0) > 0 ? 'Continue' : 'Render final film'}</Button></>}
        {busy && <><span className="type-body-sm text-muted-foreground">{st.state === 'assembling' ? 'putting it together…' : `rendering ${pct}% · piece ${st.pieces_done}/${st.pieces_total}${eta(st)}`}</span>
          <Button size="sm" onClick={() => api.stopFinal(folder)}>stop (keeps finished pieces)</Button></>}
        {st.state === 'done' && st.has_file && <a className="type-body-sm text-primary underline" href={api.finalUrl(folder)} download="film.mp4">download film.mp4</a>}
        {st.state === 'error' && <span className="type-body-sm text-danger">{st.error || 'failed'}</span>}
      </div>
      <OverlaySettings folder={folder} disabled={busy} />
      <RenderProgress progress={st.progress} busy={busy} />
      <p className="mt-2 type-caption text-muted-foreground">Rendered from the original lens video through the same camera paths, transitions and voice-over as the preview. It runs at the lowest priority and takes a long time at 4K (seconds per frame); stopping keeps what is finished.</p>
    </section>
  )
}
