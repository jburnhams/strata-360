import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { api } from '../api'
import { usePoll } from '../usePoll'
import StepVideo from './FrameStep'
import FilmStill from './FilmStill'

// A rough preview of the whole planned film (cuts, camera moves, the voice-over track). It is rendered on the server as a stream and starts playing after the first couple of seconds;
// it keeps buffering while the rest is made. A new plan or voice-over means a new preview.
export default function FilmPreview({ folder }: { folder: string }) {
  const st = usePoll(() => api.film(folder), 1500, [folder])
  const video = useRef<HTMLVideoElement>(null)
  const [err, setErr] = useState<string>()
  const key = st?.key, live = st && (st.state === 'rendering' || st.state === 'done') && (st.frames_done ?? 0) > 50
  useEffect(() => {
    const v = video.current; if (!v || !live || !key) return
    setErr(undefined); let hls: Hls | null = null, t = 0
    if (Hls.isSupported()) {
      hls = new Hls({ startPosition: 0, liveDurationInfinity: false, maxBufferLength: 60, backBufferLength: 120, manifestLoadingMaxRetry: 10, levelLoadingMaxRetry: 10 })
      hls.loadSource(api.filmUrl(folder)); hls.attachMedia(v); hls.on(Hls.Events.ERROR, (_e, d) => { if (d.fatal) setErr(d.details) })
    } else if (v.canPlayType('application/vnd.apple.mpegurl')) { v.src = api.filmUrl(folder) }
    return () => { clearTimeout(t); hls?.destroy() }
  }, [live, key, folder])
  if (!st) return null
  const pct = st.frames_total ? Math.round(100 * (st.frames_done ?? 0) / st.frames_total) : 0
  const busy = st.state === 'starting' || st.state === 'audio' || st.state === 'rendering'
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">Film preview</h3>
        {st.state === 'noplan' ? <span className="text-sm text-stone-500">Make a plan first.</span> : busy
          ? <><span className="text-sm text-stone-500">{st.state === 'rendering' ? `rendering ${pct}% (${Math.round((st.frames_done ?? 0) / 25)} of ${Math.round(st.length_s ?? 0)} s)` : 'preparing the sound…'}</span>
              <button className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => api.stopFilm(folder)}>stop</button></>
          : <button className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white" onClick={() => api.startFilm(folder, st.state === 'done')}>{st.state === 'done' ? 'Render again' : 'Render preview'}</button>}
        {st.state === 'error' && <span className="text-sm text-red-600">{st.error || 'failed'}</span>}
        {err && <span className="text-sm text-red-600">player: {err}</span>}
      </div>
      {!!st.placeholders?.length && <p className="mb-2 text-xs text-amber-700">{st.placeholders.length} clip(s) have no proxy video yet and show as dark cards: {st.placeholders.map(c => c.slice(-9)).join(', ')}. Run the processing to finish them, then render again.</p>}
      {live ? <StepVideo videoRef={video} playsInline className="aspect-video w-full max-w-3xl rounded-lg bg-black" /> : <div className="aspect-video w-full max-w-3xl rounded-lg bg-stone-100 dark:bg-stone-950" />}
      {live && <FilmStill folder={folder} video={video} planKey={key} />}
    </section>
  )
}
