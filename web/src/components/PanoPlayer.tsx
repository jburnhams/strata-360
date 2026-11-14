import { useEffect, useRef, useState } from 'react'
import { Button, SeekBar, TimeReadout, Transport, useMediaElement } from 'strata-react'
import { PanoramaViewer, type PanoramaOverlayApi, type PanoramaView } from 'strata-react/panorama'
import { aimAt, drawAim } from '../aimOverlay'
import type { AimPath } from '../api'
import { stepFrame, useFrameLength } from './FrameStep'

// A 360 video (upright equirectangular, the centre looking along the road) shown as a flat window into the sphere that you pan by dragging (touch too) and zoom with the wheel or the slider, as on the clip pages.
// The picture, the pointer and key handling and the transport are strata-react's (PanoramaViewer, useMediaElement, Transport, SeekBar); what stays here is the point camera's aim, drawn over the picture.
const HOME: PanoramaView = { yaw: 0, pitch: 0, fov: 90 }

/** A point camera's aim: a dot and the edge of its frame, through the view the viewer has now. Drawn on a canvas in the overlay slot, in the picture's own box. */
function AimLayer({ api, aim, at }: { api: PanoramaOverlayApi; aim: AimPath | null | undefined; at: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const { width, height } = api.size
  useEffect(() => {
    const c = ref.current, g = c?.getContext('2d'); if (!c || !g) return
    c.width = Math.round(width); c.height = Math.round(height)
    drawAim(g, c.width, c.height, { yaw: api.view.yaw, pitch: api.view.pitch, fov: api.view.fov, aspect: width / Math.max(height, 1) }, aimAt(aim, at))
  }, [api.view.yaw, api.view.pitch, api.view.fov, width, height, aim, at])
  return <canvas ref={ref} aria-hidden="true" data-aim-overlay="" className="pointer-events-none absolute inset-0 h-full w-full" />
}

export default function PanoPlayer({ src, label, maxPitch = 83, fps, aimPath }: { src: string; label: string; maxPitch?: number; fps?: number; aimPath?: AimPath | null }) {
  const video = useRef<HTMLVideoElement>(null)
  const [at, setAt] = useState(0)
  const m = useMediaElement(video, { onTimeUpdate: setAt })
  const [view, setView] = useState<PanoramaView>(HOME)
  const learnt = useFrameLength(video, src), frameS = () => (fps ? 1 / fps : learnt())      // (the video shows one original picture a frame, at a known rate)
  return (
    <div className="max-w-3xl">
      <video ref={video} src={src} loop muted playsInline preload="auto" className="hidden" />
      <PanoramaViewer video={video} label={`${label}: 360° view`} view={view} onViewChange={setView} maxPitch={maxPitch} minFov={30} maxFov={140} fovSlider overlay={api => <AimLayer api={api} aim={aimPath} at={at} />} />
      <Transport playing={m.playing} onPlayPause={m.toggle} onStepBack={() => stepFrame(video.current, -1, frameS())} onStepForward={() => stepFrame(video.current, 1, frameS())} className="mt-1">
        <SeekBar time={m.time} duration={m.duration} onSeek={m.seek} buffered={m.buffered} />
        <TimeReadout time={m.time} duration={m.duration} />
        <Button variant="link" size="sm" type="button" onClick={() => setView(HOME)}>Look along the road</Button>
      </Transport>
    </div>
  )
}
