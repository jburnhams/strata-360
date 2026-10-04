import { forwardRef, useEffect, useImperativeHandle, useRef, type RefObject, type VideoHTMLAttributes } from 'react'

// Stepping a video one frame at a time, wherever there is a player: pause, then a frame back or a frame forward. The length of a frame is learnt from the video itself (the gaps between the frames it shows); until then, 1/30 s.
const DEFAULT_FRAME_S = 1 / 30

/** Learns the length of one frame of a video from the times of the frames it presents. `get()` gives the current estimate. */
export function useFrameLength(video: RefObject<HTMLVideoElement | null>, src?: string) {
  const len = useRef(DEFAULT_FRAME_S)
  useEffect(() => {
    len.current = DEFAULT_FRAME_S; const v = video.current as (HTMLVideoElement & { requestVideoFrameCallback?: (cb: (now: number, m: { mediaTime: number }) => void) => number; cancelVideoFrameCallback?: (id: number) => void }) | null
    if (!v || !v.requestVideoFrameCallback) return
    let last = -1, id = 0, best = Infinity
    const tick = (_: number, m: { mediaTime: number }) => { if (last >= 0) { const d = Math.abs(m.mediaTime - last); if (d > 1e-4 && d < best) { best = d; len.current = d } } last = m.mediaTime; id = v.requestVideoFrameCallback!(tick) }
    id = v.requestVideoFrameCallback(tick); return () => v.cancelVideoFrameCallback?.(id)
  }, [video, src])
  return () => len.current
}

/** Pause and move one frame (dir -1 / +1) on the frame grid. */
export function stepFrame(v: HTMLVideoElement | null, dir: -1 | 1, frameS: number) {
  if (!v) return
  v.pause(); const max = Number.isFinite(v.duration) ? v.duration : Infinity
  v.currentTime = Math.max(0, Math.min((Math.floor(v.currentTime / frameS + 1e-3) + dir) * frameS + frameS * 0.25, max))
}

export function FrameStepButtons({ video, frameS, className = '' }: { video: RefObject<HTMLVideoElement | null>; frameS: () => number; className?: string }) {
  const b = 'rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-600'
  return (
    <span className={`inline-flex items-center gap-1 ${className}`} role="group" aria-label="Step one frame">
      <button type="button" className={b} title="Pause and go back one frame" aria-label="Previous frame" onClick={() => stepFrame(video.current, -1, frameS())}>◂ frame</button>
      <button type="button" className={b} title="Pause and go forward one frame" aria-label="Next frame" onClick={() => stepFrame(video.current, 1, frameS())}>frame ▸</button>
    </span>
  )
}

/** A video with the browser's own controls and the frame buttons under it. Takes the props of a `<video>`; `videoRef` is for a caller that needs the element. */
const StepVideo = forwardRef<HTMLVideoElement, VideoHTMLAttributes<HTMLVideoElement> & { videoRef?: RefObject<HTMLVideoElement | null> }>(function StepVideo({ videoRef, ...props }, fwd) {
  const own = useRef<HTMLVideoElement>(null); useImperativeHandle(fwd, () => own.current as HTMLVideoElement)
  const ref = videoRef ?? own, frameS = useFrameLength(ref, props.src)
  return (
    <div>
      <video {...props} ref={el => { (own as { current: HTMLVideoElement | null }).current = el; if (videoRef) (videoRef as { current: HTMLVideoElement | null }).current = el }} controls />
      <FrameStepButtons video={ref} frameS={frameS} className="mt-1" />
    </div>
  )
})
export default StepVideo
