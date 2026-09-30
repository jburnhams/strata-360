import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Player for a clip's 360 preview (upright equirect video). The thumbnail is shown first; play loads the video. The picture is a flat window into the sphere that you can pan by dragging
// (touch too) and zoom with the wheel or the slider. "Follow heading" keeps the window pointing where the runner is going (from the motion data) with your pan added on top.
const VS = `#version 300 es
in vec2 p; out vec2 uv; void main(){ uv = p; gl_Position = vec4(p, 0., 1.); }`
const FS = `#version 300 es
precision highp float; in vec2 uv; out vec4 o; uniform sampler2D tex; uniform float yaw, pitch, tanx, aspect;
const float PI = 3.14159265358979;
void main(){
  vec3 f = vec3(sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch));          // world: X right, Y forward (heading datum), Z up
  vec3 r = vec3(cos(yaw), -sin(yaw), 0.); vec3 u = cross(r, f);
  vec3 d = normalize(f + uv.x * tanx * r + uv.y * tanx / aspect * u);
  float lon = atan(d.x, d.y), lat = asin(clamp(d.z, -1., 1.));
  o = texture(tex, vec2(lon / (2. * PI) + .5, .5 - lat / PI));
}`
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export default function ClipPlayer({ folder, clip, thumbKind, heading, hasPreview, duration }: {
  folder: string; clip: string; thumbKind?: string; heading?: { t: number[]; deg: number[] } | null; hasPreview: boolean; duration: number
}) {
  const video = useRef<HTMLVideoElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const st = useRef({ yaw: 0, pitch: 0, fov: 100, follow: true, gl: null as null | { draw: () => void }, raf: 0 })
  const [started, setStarted] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [t, setT] = useState(0)
  const [follow, setFollow] = useState(true)
  const [fov, setFov] = useState(100)
  const [muted, setMuted] = useState(false)
  const [rate, setRate] = useState(1)
  const [err, setErr] = useState<string>()

  const headingAt = useCallback((time: number) => {
    if (!heading || !heading.t.length) return 0
    const { t: ts, deg } = heading; let lo = 0, hi = ts.length - 1
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= time) lo = m; else hi = m }
    const a = ts[lo], b = ts[hi], w = b > a ? Math.min(Math.max((time - a) / (b - a), 0), 1) : 0
    return ((deg[lo] + (deg[hi] - deg[lo]) * w) * Math.PI) / 180
  }, [heading])

  // WebGL: one full-screen triangle pair; the video frame is the texture, the shader turns each pixel into a ray into the sphere.
  useEffect(() => {
    if (!started || !canvas.current || !video.current) return
    const cv = canvas.current, v = video.current, gl = cv.getContext('webgl2')
    if (!gl) { setErr('WebGL 2 is not available in this browser'); return }
    const sh = (type: number, src: string) => { const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s); return s }
    const prog = gl.createProgram()!; gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog); gl.useProgram(prog)
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
    const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex)
    for (const [k, val] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.REPEAT], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]] as const) gl.texParameteri(gl.TEXTURE_2D, k, val)
    const U = (n: string) => gl.getUniformLocation(prog, n)
    const draw = () => {
      const w = cv.clientWidth * devicePixelRatio, h = cv.clientHeight * devicePixelRatio
      if (cv.width !== Math.round(w) || cv.height !== Math.round(h)) { cv.width = Math.round(w); cv.height = Math.round(h) }
      gl.viewport(0, 0, cv.width, cv.height)
      if (v.readyState >= 2) { gl.bindTexture(gl.TEXTURE_2D, tex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, v) }
      const s = st.current, yaw = s.yaw + (s.follow ? headingAt(v.currentTime) : 0)
      gl.uniform1f(U('yaw'), yaw); gl.uniform1f(U('pitch'), s.pitch); gl.uniform1f(U('tanx'), Math.tan((s.fov * Math.PI) / 360)); gl.uniform1f(U('aspect'), cv.width / cv.height)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    }
    st.current.gl = { draw }
    const loop = () => { draw(); st.current.raf = requestAnimationFrame(loop) }
    loop()
    return () => { cancelAnimationFrame(st.current.raf); st.current.gl = null }
  }, [started, headingAt])

  useEffect(() => { st.current.follow = follow }, [follow])
  useEffect(() => { st.current.fov = fov }, [fov])
  useEffect(() => { setStarted(false); setPlaying(false); setT(0); setErr(undefined); st.current.yaw = 0; st.current.pitch = 0 }, [clip])

  const drag = useRef<{ x: number; y: number } | null>(null)
  const onDown = (e: React.PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY }; (e.target as HTMLElement).setPointerCapture(e.pointerId) }
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const k = (st.current.fov * Math.PI) / 180 / (canvas.current?.clientWidth || 800)                                  // radians per pixel at the current zoom
    st.current.yaw -= (e.clientX - drag.current.x) * k; st.current.pitch = Math.max(-1.45, Math.min(1.45, st.current.pitch + (e.clientY - drag.current.y) * k)); drag.current = { x: e.clientX, y: e.clientY }
  }
  const onWheel = (e: React.WheelEvent) => setFov(f => Math.max(40, Math.min(120, f + e.deltaY * 0.05)))
  const reset = () => { st.current.yaw = 0; st.current.pitch = 0; setFov(100) }

  const play = async () => {
    const v = video.current; if (!v) return
    if (!started) { setStarted(true); await new Promise(r => setTimeout(r, 50)) }
    if (v.paused) { try { await video.current!.play() } catch (e) { setErr((e as Error).message) } } else v.pause()
  }
  const noPreview = !hasPreview

  return (
    <div className="overflow-hidden rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <div className="relative aspect-video w-full bg-black">
        {thumbKind && !started && <img src={api.thumbUrl(folder, clip, thumbKind)} alt="" className="absolute inset-0 h-full w-full object-cover" />}
        <video ref={video} src={started ? api.previewUrl(folder, clip) : undefined} muted={muted} playsInline preload="auto" crossOrigin="anonymous" className="hidden"
          onTimeUpdate={e => setT((e.target as HTMLVideoElement).currentTime)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => setErr('could not load the preview video')} />
        <canvas ref={canvas} className={`absolute inset-0 h-full w-full cursor-grab touch-none active:cursor-grabbing ${started ? '' : 'hidden'}`}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => (drag.current = null)} onPointerCancel={() => (drag.current = null)} onWheel={onWheel} onDoubleClick={reset} />
        {!started && (
          <button disabled={noPreview} onClick={play} className="absolute inset-0 grid place-items-center disabled:cursor-not-allowed" aria-label="Play">
            <span className={`grid h-16 w-16 place-items-center rounded-full bg-black/60 text-3xl text-white ${noPreview ? 'opacity-40' : 'hover:bg-emerald-700'}`}>▶</span>
          </button>
        )}
        {noPreview && <div className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs text-white">the preview video has not been made for this clip yet (the preview stage)</div>}
        {err && <div className="absolute bottom-2 left-2 rounded bg-red-700/90 px-2 py-1 text-xs text-white">{err}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
        <button disabled={noPreview} onClick={play} className="w-9 rounded bg-emerald-700 py-1 text-white disabled:opacity-40" aria-label={playing ? 'Pause' : 'Play'}>{playing ? '❚❚' : '▶'}</button>
        <span className="w-24 font-mono text-xs text-stone-500">{mmss(t)} / {mmss(duration)}</span>
        <input type="range" min={0} max={duration} step={0.04} value={t} disabled={!started} className="min-w-32 flex-1"
          onChange={e => { const v = video.current; if (v) { v.currentTime = Number(e.target.value); setT(v.currentTime) } }} aria-label="Seek" />
        <button className="text-xs" disabled={!started} onClick={() => setMuted(m => !m)} title="sound">{muted ? '🔇' : '🔊'}</button>
        <select value={rate} disabled={!started} onChange={e => { const r = Number(e.target.value); setRate(r); if (video.current) video.current.playbackRate = r }} className="rounded border border-stone-300 bg-transparent px-1 text-xs dark:border-stone-700">
          {[0.5, 1, 1.5, 2].map(r => <option key={r} value={r}>{r}×</option>)}</select>
        <label className="flex items-center gap-1 text-xs" title="Keep the view pointing where the runner is heading"><input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)} />follow heading</label>
        <label className="flex items-center gap-1 text-xs" title="Field of view (or use the mouse wheel)">view<input type="range" min={40} max={120} value={fov} onChange={e => setFov(Number(e.target.value))} className="w-20" />{Math.round(fov)}°</label>
        <button className="text-xs underline" onClick={reset} title="Reset the view (or double-click the picture)">reset view</button>
      </div>
    </div>
  )
}
