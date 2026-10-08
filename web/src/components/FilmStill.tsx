import { useState, type RefObject } from 'react'
import { api, type EnlargeMode } from '../api'
import { usePoll } from '../usePoll'
import RenderProgress from './RenderProgress'
import StillGallery from './StillGallery'
import { ENLARGE, SIZES, clock, enlargeShort, sizeLabel } from './stillModes'

// Final-quality stills of the film. They go through the final render's own pipeline (the original two-lens video, camera path, exposure match, map overlay, transitions), so they are slow (seconds, and a long first time for a clip it has not seen) and
// run at the lowest priority, one after the other; the same frame at the same size and enlarging is only made once. "Auto" picks a series of differing moments through the film. Everything made is kept: the gallery below shows all of it.
export default function FilmStill({ folder, video, planKey }: { folder: string; video: RefObject<HTMLVideoElement | null>; planKey?: string }) {
  const [size, setSize] = useState('3840x2160'), [up, setUp] = useState<EnlargeMode>('off'), [err, setErr] = useState<string>(), [sent, setSent] = useState(0)
  const list = usePoll(() => api.filmStills(folder), 2000, [folder, planKey, sent])
  const active = list?.active ?? [], busy = active.some(a => a.state === 'queued' || a.state === 'rendering')
  const running = active.find(a => a.state === 'rendering') ?? active.find(a => a.state === 'queued'), failed = active.filter(a => a.state === 'error')
  const send = (call: Promise<unknown>) => { setErr(undefined); call.then(() => setSent(n => n + 1)).catch(e => setErr(e instanceof Error ? e.message : String(e))) }
  const here = () => send(api.startFilmStill(folder, video.current?.currentTime ?? 0, size, up))
  const auto = () => send(api.startFilmStills(folder, { size, upscale: up, auto: true }))
  const sel = 'rounded-lg border border-stone-300 bg-stone-50 px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-950'
  const n = list?.auto_count ?? 0, queued = active.filter(a => a.state === 'queued' || a.state === 'rendering').length
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-3">
        <h4 className="text-sm font-semibold">Final stills</h4>
        <label className="text-sm">Size <select className={sel} value={size} onChange={e => setSize(e.target.value)}>{SIZES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="text-sm" title="Runs the local upscaling model on a shot that holds too few pixels (not at night). The lower modes work to 1080p or 1440p and then resample to the size: much quicker than the model all the way.">Enlarge <select className={sel} value={up} onChange={e => setUp(e.target.value as EnlargeMode)}>{ENLARGE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <button className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white" onClick={here}>Render still at the player position</button>
        <button className="rounded-lg border border-emerald-700 px-3 py-1.5 text-sm text-emerald-800 disabled:opacity-50 dark:text-emerald-300" disabled={!n} onClick={auto} title="A series of differing moments spread over the film: 4 for a film of 2 minutes, up to 10 at 30 minutes and more. Each moment is the middle of a shot that differs from the others in clip, how tight it is and its kind.">Auto: {n || '…'} differing moments</button>
        {busy && <span className="text-sm text-stone-500" role="status">{queued} {queued === 1 ? 'still' : 'stills'} to go{running?.t !== undefined ? ` · now the frame at ${clock(running.t)}` : ''}{running?.upscale ? ` (${enlargeShort(running.upscale)})` : ''}{running?.size ? ` · ${sizeLabel(running.size)}` : ''}</span>}
        {err && <span className="text-sm text-red-600" role="alert">{err}</span>}
      </div>
      {failed.map(f => <p key={f.name} className="mt-1 text-sm text-red-600" role="alert">{f.t !== undefined ? `The still at ${clock(f.t)} failed: ` : 'A still failed: '}{f.error || 'the render failed'}</p>)}
      {running && <RenderProgress progress={running.progress} busy />}
      <StillGallery folder={folder} stills={list?.stills ?? []} active={active} loading={!list} />
      <p className="mt-1 max-w-3xl text-xs text-stone-500">Made like the final film (original video, camera path, exposure match, overlay, transitions) at the lowest priority, one after the other. The first still of a clip can take many minutes while the clip's data is prepared; after that, seconds. Stills made from an older plan are kept and marked.</p>
    </div>
  )
}
