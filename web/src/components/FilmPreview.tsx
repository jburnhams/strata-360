import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { api } from '../api'
import { usePoll } from '../usePoll'
import StepVideo from './FrameStep'
import FilmStill from './FilmStill'
import { Button } from 'strata-react'

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
    <section className="rounded-overlay border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h3 className="type-body-sm font-semibold">Film preview</h3>
        {st.state === 'noplan' ? <span className="type-body-sm text-muted-foreground">Make a plan first.</span> : busy
          ? <><span className="type-body-sm text-muted-foreground">{st.state === 'rendering' ? `rendering ${pct}% (${Math.round((st.frames_done ?? 0) / 25)} of ${Math.round(st.length_s ?? 0)} s)` : 'preparing the sound…'}</span>
              <Button size="sm" onClick={() => api.stopFilm(folder)}>stop</Button></>
          : <Button variant="default" onClick={() => api.startFilm(folder, st.state === 'done')}>{st.state === 'done' ? 'Render again' : 'Render preview'}</Button>}
        {st.state === 'error' && <span className="type-body-sm text-danger">{st.error || 'failed'}</span>}
        {err && <span className="type-body-sm text-danger">player: {err}</span>}
      </div>
      {!!st.placeholders?.length && <p className="mb-2 type-caption text-warning">{st.placeholders.length} clip(s) have no proxy video yet and show as dark cards: {st.placeholders.map(c => c.slice(-9)).join(', ')}. Run the processing to finish them, then render again.</p>}
      {live ? <StepVideo videoRef={video} playsInline className="aspect-video w-full max-w-3xl rounded-surface bg-black" /> : <div className="aspect-video w-full max-w-3xl rounded-surface bg-muted" />}
      {live && <FilmStill folder={folder} video={video} planKey={key} />}
    </section>
  )
}
