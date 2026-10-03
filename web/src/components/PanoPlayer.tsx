import { useCallback, useEffect, useRef, useState } from 'react'

// A 360 video (upright equirectangular, the centre looking along the road) shown as a flat window into the sphere that you pan by dragging (touch too) and zoom with the wheel or the slider, as on the clip pages.
const VS = `#version 300 es
in vec2 p; out vec2 uv; void main(){ uv = p; gl_Position = vec4(p, 0., 1.); }`
const FS = `#version 300 es
precision highp float; in vec2 uv; out vec4 o; uniform sampler2D tex; uniform float yaw, pitch, tanx, aspect;
const float PI = 3.14159265358979;
void main(){
  vec3 f = vec3(sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch));
  vec3 r = vec3(cos(yaw), -sin(yaw), 0.); vec3 u = cross(r, f);
  vec3 d = normalize(f + uv.x * tanx * r + uv.y * tanx / aspect * u);
  float lon = atan(d.x, d.y), lat = asin(clamp(d.z, -1., 1.));
  o = texture(tex, vec2(lon / (2. * PI) + .5, .5 - lat / PI));
}`
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export default function PanoPlayer({ src, label, maxPitch = 83 }: { src: string; label: string; maxPitch?: number }) {
  const cv = useRef<HTMLCanvasElement>(null), video = useRef<HTMLVideoElement>(null), st = useRef({ yaw: 0, pitch: 0, fov: 90, drag: null as null | { x: number; y: number }, raf: 0 })
  const [fov, setFov] = useState(90), [playing, setPlaying] = useState(false), [t, setT] = useState(0), [dur, setDur] = useState(0), [gl, setGl] = useState(true)
  useEffect(() => {
    const c = cv.current, v = video.current; if (!c || !v) return
    const g = c.getContext('webgl2'); if (!g) { setGl(false); return }
    const sh = (type: number, s: string) => { const o = g.createShader(type)!; g.shaderSource(o, s); g.compileShader(o); return o }
    const pr = g.createProgram()!; g.attachShader(pr, sh(g.VERTEX_SHADER, VS)); g.attachShader(pr, sh(g.FRAGMENT_SHADER, FS)); g.linkProgram(pr); g.useProgram(pr)
    const buf = g.createBuffer(); g.bindBuffer(g.ARRAY_BUFFER, buf); g.bufferData(g.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), g.STATIC_DRAW)
    const loc = g.getAttribLocation(pr, 'p'); g.enableVertexAttribArray(loc); g.vertexAttribPointer(loc, 2, g.FLOAT, false, 0, 0)
    const tex = g.createTexture(); g.bindTexture(g.TEXTURE_2D, tex); for (const [k, val] of [[g.TEXTURE_MIN_FILTER, g.LINEAR], [g.TEXTURE_MAG_FILTER, g.LINEAR], [g.TEXTURE_WRAP_S, g.REPEAT], [g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE]]) g.texParameteri(g.TEXTURE_2D, k, val)
    const U = (n: string) => g.getUniformLocation(pr, n)
    const draw = () => {
      const s = st.current; if (c.width !== c.clientWidth || c.height !== c.clientHeight) { c.width = c.clientWidth; c.height = c.clientHeight; g.viewport(0, 0, c.width, c.height) }
      if (v.readyState >= 2) { g.bindTexture(g.TEXTURE_2D, tex); g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, v) }
      g.uniform1f(U('yaw'), s.yaw); g.uniform1f(U('pitch'), s.pitch); g.uniform1f(U('tanx'), Math.tan((s.fov * Math.PI) / 360)); g.uniform1f(U('aspect'), c.width / Math.max(c.height, 1)); g.drawArrays(g.TRIANGLE_STRIP, 0, 4)
      s.raf = requestAnimationFrame(draw)
    }
    st.current.raf = requestAnimationFrame(draw); return () => cancelAnimationFrame(st.current.raf)
  }, [src])
  const down = (e: React.PointerEvent) => { st.current.drag = { x: e.clientX, y: e.clientY }; (e.target as HTMLElement).setPointerCapture?.(e.pointerId) }
  const move = (e: React.PointerEvent) => {
    const s = st.current, d = s.drag; if (!d) return; const w = cv.current?.clientWidth || 1, k = (s.fov * Math.PI) / 180 / w          // radians a pixel turns the view
    s.yaw -= (e.clientX - d.x) * k; const lim = (maxPitch * Math.PI) / 180; s.pitch = Math.max(-lim, Math.min(lim, s.pitch + (e.clientY - d.y) * k)); s.drag = { x: e.clientX, y: e.clientY }
  }
  const up = () => { st.current.drag = null }
  const zoom = useCallback((f: number) => { const v = Math.max(30, Math.min(140, f)); st.current.fov = v; setFov(v) }, [])
  const toggle = () => { const v = video.current; if (!v) return; if (v.paused) v.play(); else v.pause() }
  return (
    <div aria-label={`${label}: look around`} className="max-w-3xl">
      <video ref={video} src={src} loop muted playsInline preload="auto" className="hidden" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onTimeUpdate={e => setT(e.currentTarget.currentTime)} onLoadedMetadata={e => setDur(e.currentTarget.duration)} />
      {gl ? <canvas ref={cv} role="img" aria-label="360° view: drag to look around" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onWheel={e => zoom(st.current.fov + (e.deltaY > 0 ? 6 : -6))} className="aspect-video w-full cursor-grab touch-none rounded bg-black active:cursor-grabbing" />
        : <p className="text-sm text-stone-500">This browser cannot show a 360° view.</p>}
      <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-stone-600 dark:text-stone-400">
        <button type="button" onClick={toggle} className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-600">{playing ? 'Pause' : 'Play'}</button>
        <input aria-label="Position" type="range" min={0} max={dur || 1} step={0.05} value={t} onChange={e => { if (video.current) video.current.currentTime = Number(e.target.value) }} className="w-48" /> <span>{mmss(t)} / {mmss(dur)}</span>
        <label className="flex items-center gap-1">Zoom <input aria-label="Zoom" type="range" min={30} max={140} step={1} value={170 - fov} onChange={e => zoom(170 - Number(e.target.value))} className="w-24" /></label>
        <button type="button" onClick={() => { st.current.yaw = 0; st.current.pitch = 0; zoom(90) }} className="underline">Look along the road</button>
        <span>drag to look around · wheel to zoom</span>
      </div>
    </div>
  )
}
