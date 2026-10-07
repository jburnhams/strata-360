import { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../usePoll'

const eta = (st: { frames_done?: number; frames_total?: number; started?: number }) => {
  if (!st.frames_done || !st.frames_total || !st.started) return ''
  const secs = (Date.now() / 1000 - st.started) * (st.frames_total - st.frames_done) / st.frames_done
  return secs > 90 ? ` · about ${Math.round(secs / 60)} min left` : ''
}

// The final film: rendered from the original video at full quality (slow, at the lowest priority, resumable: pieces that are finished are kept if you stop it or the plan is unchanged).
export default function FinalRender({ folder }: { folder: string }) {
  const st = usePoll(() => api.final(folder), 3000, [folder])
  const [size, setSize] = useState<string>(), [fps, setFps] = useState<number>(), [half, setHalf] = useState<boolean>()
  if (!st || st.state === 'noplan') return null
  const busy = st.state === 'starting' || st.state === 'rendering' || st.state === 'assembling'
  const pct = st.frames_total ? Math.round(100 * (st.frames_done ?? 0) / st.frames_total) : 0
  const sel = 'rounded-lg border border-stone-300 bg-stone-50 px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-950'
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">Final film</h3>
        {!busy && <>
          <label className="text-sm">Size <select className={sel} value={size ?? st.settings.size} onChange={e => setSize(e.target.value)}><option value="1920x1080">1080p</option><option value="2560x1440">1440p</option><option value="3840x2160">4K</option></select></label>
          <label className="text-sm">Frames/s <select className={sel} value={fps ?? st.settings.fps} onChange={e => setFps(Number(e.target.value))}><option value={0}>the footage's own</option><option value={25}>25</option><option value={30}>30</option><option value={50}>50</option></select></label>
          <label className="text-sm"><input type="checkbox" checked={half ?? st.settings.half_rate} onChange={e => setHalf(e.target.checked)} /> Half frame rate (faster)</label>
          <button className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white" onClick={() => api.startFinal(folder, { size: size ?? st.settings.size, fps: fps ?? st.settings.fps, half_rate: half ?? st.settings.half_rate })}>{st.state === 'done' ? 'Render again' : st.state === 'stopped' || (st.pieces_done ?? 0) > 0 ? 'Continue' : 'Render final film'}</button></>}
        {busy && <><span className="text-sm text-stone-500">{st.state === 'assembling' ? 'putting it together…' : `rendering ${pct}% · piece ${st.pieces_done}/${st.pieces_total}${eta(st)}`}</span>
          <button className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => api.stopFinal(folder)}>stop (keeps finished pieces)</button></>}
        {st.state === 'done' && st.has_file && <a className="text-sm text-emerald-700 underline dark:text-emerald-400" href={api.finalUrl(folder)} download="film.mp4">download film.mp4</a>}
        {st.state === 'error' && <span className="text-sm text-red-600">{st.error || 'failed'}</span>}
      </div>
      <p className="mt-2 text-xs text-stone-500">Rendered from the original lens video through the same camera paths, transitions and voice-over as the preview. It runs at the lowest priority and takes a long time at 4K (seconds per frame); stopping keeps what is finished.</p>
    </section>
  )
}
