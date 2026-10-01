import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Follower, aimPitch, vfovDeg } from '../aim'
import { useThumbOverlay } from '../thumbOverlay'

// Player for a clip's 360 preview (upright equirect video). The thumbnail is shown first; play loads the video. The picture is a flat window into the sphere that you can pan by dragging
// (touch too) and zoom with the wheel or the slider. Four ways to aim: Free (stays where you put it), Heading (points where the runner is going, from the motion data), You (turns to the wearer) and Person
// (always another person, staying with the same one as long as possible and jumping as little as it can) and Clarity (the part of the picture with the most detail, contrast and colour, from the view-quality maps). In the automatic modes your pan is added on top and eases back when you switch.
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

type Focus = { t: number; yaw: number; pitch: number; height?: number | null; head?: number | null; who: 'you' | 'other'; speaking: boolean; person?: number }
type Aim = 'free' | 'heading' | 'you' | 'person' | 'clarity'
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a))

export default function ClipPlayer({ folder, clip, thumbKind, heading, focus, person, clarity, hasPreview, duration, window: win, autoStart }: {
  folder: string; clip: string; thumbKind?: string; heading?: { t: number[]; deg: number[] } | null; focus?: Focus[] | null; person?: Focus[] | null; clarity?: { t: number; yaw: number; pitch: number }[] | null; hasPreview: boolean; duration: number
  window?: { start: number; end: number }; autoStart?: boolean   // play only this part of the clip (the timeline's window); autoStart begins at once
}) {
  const video = useRef<HTMLVideoElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const st = useRef({ yaw: 0, pitch: 0, fov: 100, aim: 'heading' as Aim, tyaw: 0, tpitch: 0, decay: 0, cur: 0, fol: null as null | Follower, folAim: '' as string, lastT: 0, lastMs: 0, active: 0, gl: null as null | { draw: () => void }, raf: 0 })
  const [started, setStarted] = useState(false)
  const [overlay] = useThumbOverlay()
  const [playing, setPlaying] = useState(false)
  const [t, setT] = useState(0)
  const [aim, setAim] = useState<Aim>('heading')
  const [shown, setShown] = useState<string>('')
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

  const youList = focus
  // The person to look at: interpolate the once-a-second samples (angles unwrapped); no sample within 2 s means nobody to follow, and the view falls back to the heading.
  const focusAt = useCallback((time: number, mode: Aim = 'you') => {
    const focus = (mode === 'person' ? person : mode === 'clarity' ? clarity : youList) as Focus[] | null | undefined
    if (!focus || !focus.length) return null
    let lo = -1; for (let i = 0; i < focus.length; i++) if (focus[i].t <= time) lo = i
    const a = focus[Math.max(lo, 0)], b = focus[Math.min(lo + 1, focus.length - 1)]
    if (Math.abs(a.t - time) > 2 && Math.abs(b.t - time) > 2) return null
    const w = b.t > a.t ? Math.min(Math.max((time - a.t) / (b.t - a.t), 0), 1) : 0, ay = (a.yaw * Math.PI) / 180, by = (b.yaw * Math.PI) / 180
    return { yaw: ay + wrap(by - ay) * w, pitch: (((a.pitch + (b.pitch - a.pitch) * w) * Math.PI) / 180), height: a.height ?? b.height, head: a.head ?? b.head, who: (w < 0.5 ? a : b).who, speaking: (w < 0.5 ? a : b).speaking }
  }, [youList, person, clarity])

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
      const s = st.current, now = v.currentTime, hd = headingAt(now)
      let baseYaw = 0, basePitch = 0, follow = false
      const ms = performance.now(), dts = Math.min(Math.max((ms - s.lastMs) / 1000, 0), 0.1); s.lastMs = ms
      if (s.aim === 'heading') baseYaw = hd
      else if (s.aim === 'you' || s.aim === 'person' || s.aim === 'clarity') {
        const f = focusAt(now, s.aim)
        if (f) {                                                                                       // a steady follower: holds, pans slowly, or moves once when the person goes far; the head sits near the top of the frame
          const ty = (f.yaw * 180) / Math.PI, tp = s.aim === 'clarity' ? (f.pitch * 180) / Math.PI : aimPitch((f.pitch * 180) / Math.PI, f.height, vfovDeg(s.fov, cv.width / cv.height), f.head)
          if (!s.fol || s.folAim !== s.aim || Math.abs(now - s.lastT) > 1) { s.fol = new Follower(ty, tp); s.folAim = s.aim }
          const [fy, fp] = s.fol.step(ty, tp, dts); baseYaw = (fy * Math.PI) / 180; basePitch = (fp * Math.PI) / 180; follow = true; s.cur = baseYaw
        } else { s.fol = null; baseYaw = hd }
      }
      s.lastT = now
      if (s.aim !== 'free') {
        if (!follow) { const d = wrap(baseYaw - s.cur); s.cur = s.cur + d * 0.12; baseYaw = s.cur }          // heading (and nobody found): ease towards the target
        if (s.decay > 0) { s.yaw *= 0.9; s.pitch *= 0.9; s.decay -= 1 }                               // after a mode switch the manual offset eases back to the automatic aim
      } else s.cur = baseYaw
      const yaw = s.yaw + baseYaw, pitch = Math.max(-1.45, Math.min(1.45, s.pitch + (follow ? basePitch : 0)))
      gl.uniform1f(U('yaw'), yaw); gl.uniform1f(U('pitch'), pitch); gl.uniform1f(U('tanx'), Math.tan((s.fov * Math.PI) / 360)); gl.uniform1f(U('aspect'), cv.width / cv.height)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    }
    st.current.gl = { draw }
    // Draw every frame only while something is happening (playing, dragging, zooming, a switch of aim, the follower still moving); when the picture is idle, and whenever the tab is hidden, a few checks a second: an
    // open but untouched player must not use a CPU core (and the GPU) for ever.
    const loop = () => {
      const s = st.current, idle = v.paused && !drag.current && performance.now() - s.active > 1500 && Math.abs(v.currentTime - s.lastT) < 0.001      // a scrub moves the time: that wakes it
      if (document.hidden || idle) { s.raf = window.setTimeout(loop, document.hidden ? 1000 : 250) as unknown as number; return }
      draw(); s.raf = requestAnimationFrame(loop)
    }
    loop()
    return () => { cancelAnimationFrame(st.current.raf); clearTimeout(st.current.raf); st.current.gl = null }
  }, [started, headingAt, focusAt])

  // Switching mode keeps the picture where it is: the current aim becomes the manual offset, which then eases back for the automatic modes (Free keeps it).
  const changeAim = (next: Aim) => {
    wake()
    const s = st.current, v = video.current, now = v?.currentTime ?? 0; const cur = s.yaw + (s.aim === 'free' ? 0 : s.cur)
    const base = next === 'free' ? 0 : next === 'heading' ? headingAt(now) : (focusAt(now, next)?.yaw ?? headingAt(now))
    s.yaw = wrap(cur - (next === 'free' ? 0 : base)); s.cur = base; s.fol = null; s.aim = next; s.decay = next === 'free' ? 0 : 45; setAim(next)
  }
  useEffect(() => { const id = setInterval(() => { const a = st.current.aim, f = a === 'you' || a === 'person' || a === 'clarity' ? focusAt(video.current?.currentTime ?? 0, a) : null; setShown(a === 'clarity' ? (f ? 'the clearest part of the picture' : 'no quality map for this clip yet (the exposure stage): following the heading') : a === 'you' || a === 'person' ? (f ? (a === 'you' ? (f.speaking ? 'you (speaking)' : 'you') : f.speaking ? 'another person (someone is speaking)' : 'another person') : a === 'you' ? 'you are not in view: following the heading' : 'nobody else in view: following the heading') : '') }, 500); return () => clearInterval(id) }, [focusAt, headingAt])
  useEffect(() => { st.current.fov = fov; st.current.active = performance.now() }, [fov])
  useEffect(() => { setStarted(false); setPlaying(false); setT(0); setErr(undefined); st.current.yaw = 0; st.current.pitch = 0 }, [clip])

  const drag = useRef<{ x: number; y: number } | null>(null)
  const wake = () => { st.current.active = performance.now() }
  const onDown = (e: React.PointerEvent) => { wake(); drag.current = { x: e.clientX, y: e.clientY }; (e.target as HTMLElement).setPointerCapture(e.pointerId) }
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const k = (st.current.fov * Math.PI) / 180 / (canvas.current?.clientWidth || 800)                                  // radians per pixel at the current zoom
    st.current.yaw -= (e.clientX - drag.current.x) * k; st.current.pitch = Math.max(-1.45, Math.min(1.45, st.current.pitch + (e.clientY - drag.current.y) * k)); drag.current = { x: e.clientX, y: e.clientY }
  }
  const onWheel = (e: React.WheelEvent) => wake() ?? setFov(f => Math.max(40, Math.min(120, f + e.deltaY * 0.05)))
  const reset = () => { wake(); st.current.yaw = 0; st.current.pitch = 0; st.current.decay = 0; setFov(100) }

  const play = async () => {
    const v = video.current; if (!v) return
    if (!started) { setStarted(true); await new Promise(r => setTimeout(r, 50)) }
    if (win && (v.currentTime < win.start - 0.05 || v.currentTime >= win.end - 0.05)) v.currentTime = win.start
    if (v.paused) { try { await video.current!.play() } catch (e) { setErr((e as Error).message) } } else v.pause()
  }
  useEffect(() => { if (autoStart && hasPreview && !started) play() }, [autoStart, hasPreview])   // eslint-disable-line react-hooks/exhaustive-deps
  const noPreview = !hasPreview

  return (
    <div className="overflow-hidden rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <div className="relative aspect-video w-full bg-black">
        {thumbKind && !started && <img src={api.thumbUrl(folder, clip, thumbKind + (overlay ? '+overlay' : ''), overlay)} alt="" className="absolute inset-0 h-full w-full object-cover" />}
        <video ref={video} src={started ? api.previewUrl(folder, clip) : undefined} muted={muted} playsInline preload="auto" crossOrigin="anonymous" className="hidden"
          onLoadedMetadata={e => { if (win) (e.target as HTMLVideoElement).currentTime = win.start }}
          onTimeUpdate={e => { const v = e.target as HTMLVideoElement; setT(v.currentTime); if (win && v.currentTime >= win.end) { v.pause(); v.currentTime = win.start } }} onPlay={() => { setPlaying(true); st.current.active = performance.now() }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => setErr('could not load the preview video')} />
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
        <span className="inline-flex overflow-hidden rounded border border-stone-300 text-xs dark:border-stone-700" role="group" aria-label="Where the view points">
          {([['free', 'Free', 'stays where you put it'], ['heading', 'Heading', 'points where the runner is going'], ['you', 'You', 'turns to you, the wearer'], ['person', 'Person', 'always another person: stays with the same one as long as it can, and jumps as little as possible'], ['clarity', 'Clarity', 'the part of the picture with the most detail, contrast and colour (and away from a foggy lens): holds, pans slowly, or moves once']] as const).map(([k, label, tip]) => (
            <button key={k} title={tip} disabled={(k === 'you' && !focus?.length) || (k === 'person' && !person?.length) || (k === 'clarity' && !clarity?.length)} onClick={() => changeAim(k)} className={`px-2 py-0.5 disabled:opacity-40 ${aim === k ? 'bg-emerald-700 text-white' : ''}`}>{label}</button>))}
        </span>
        {shown && <span className="text-xs text-stone-500">showing {shown}</span>}
        <label className="flex items-center gap-1 text-xs" title="Field of view (or use the mouse wheel)">view<input type="range" min={40} max={120} value={fov} onChange={e => setFov(Number(e.target.value))} className="w-20" />{Math.round(fov)}°</label>
        <button className="text-xs underline" onClick={reset} title="Reset the view (or double-click the picture)">reset view</button>
      </div>
    </div>
  )
}
