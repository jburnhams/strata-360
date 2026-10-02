import { useEffect, useRef, useState } from 'react'
import { api, type MusicAnalysis } from '../api'
import { usePoll } from '../usePoll'

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The film's music track (music.json): tempo, bar line and loudness drive the plan (cuts on the beat, calm and busy parts follow the music) and it is mixed under the voice-over, from its first downbeat.
// Unset: an upload button. Set: a player, the waveform and spectrogram with the bar lines and the first downbeat marked (click to seek), the energy by bar, and a link to change the track.
export default function MusicPanel({ folder, onChanged }: { folder: string; onChanged?: () => void }) {
  const [ver, setVer] = useState(0)
  const st = usePoll(() => api.music(folder), 30000, [folder, ver])
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<string>()
  const pick = async (f?: File) => { if (!f) return; setBusy(true); setMsg(undefined); try { const r = await api.uploadMusic(folder, f); if (r.warning) setMsg(r.warning) } catch (e) { setMsg((e as Error).message) } setBusy(false); setVer(v => v + 1); onChanged?.() }
  const a = st?.analysis
  const picker = (label: string, cls: string) => <label className={`cursor-pointer ${cls}`}>{busy ? 'analysing…' : label}<input type="file" accept="audio/*" className="hidden" disabled={busy} onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }} /></label>
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">Music</h3>
        {st?.file ? <>
          <span className="max-w-[24rem] truncate text-sm" title={st.name ?? st.file}>{st.name ?? st.file}</span>
          {picker('change', 'text-xs text-emerald-700 underline dark:text-emerald-400')}
          <button className="text-xs underline" onClick={async () => { await api.removeMusic(folder); setVer(v => v + 1); onChanged?.() }}>remove</button>
        </> : st && picker('Upload a track', 'rounded-lg border border-stone-300 px-3 py-1.5 text-sm dark:border-stone-700')}
        {a && <span className="text-sm text-stone-500">{a.bpm} bpm · first bar at {a.offset_s.toFixed(1)} s · {Math.round(a.duration_s)} s long{a.confidence < 0.4 && <span className="text-amber-700"> · the beat is uncertain (tempo may change in this track)</span>}</span>}
      </div>
      {st?.file && <TrackView folder={folder} a={a} peaks={st.waveform ?? undefined} v={`${st.name}-${a?.duration_s}-${ver}`} />}
      {st?.file && !a && <p className="mt-2 text-sm text-amber-700">This track could not be read; try another file.</p>}
      {msg && <p className="mt-2 text-sm text-amber-700">{msg}</p>}
      {st && !st.file && <p className="mt-2 text-xs text-stone-500">Optional. Without a track the plan uses a steady 120 bpm.</p>}
    </section>
  )
}

function TrackView({ folder, a, peaks, v }: { folder: string; a?: MusicAnalysis | null; peaks?: number[]; v: string }) {
  const audio = useRef<HTMLAudioElement>(null), [t, setT] = useState(0), [playing, setPlaying] = useState(false)
  useEffect(() => {
    if (!playing) return
    let raf = 0; const tick = () => { setT(audio.current?.currentTime ?? 0); raf = requestAnimationFrame(tick) }; raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf)
  }, [playing])
  const dur = a?.duration_s ?? 0
  const bars: number[] = []
  if (a && dur > 0) { const bar = (60 / a.bpm) * (a.bar_beats ?? 4); for (let x = a.offset_s; x < dur && bars.length < 600; x += bar) bars.push(x / dur) }
  const seek = (e: React.MouseEvent<HTMLDivElement>) => { const r = e.currentTarget.getBoundingClientRect(); if (audio.current && dur > 0) { audio.current.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * dur; setT(audio.current.currentTime) } }
  const wave = peaks?.length ? 'M0 30 ' + peaks.map((p, i) => `L${(i * 1000) / peaks.length} ${30 - 29 * p}`).join(' ') + ` L1000 30 ` + [...peaks].reverse().map((p, i) => `L${1000 - (i * 1000) / peaks.length} ${30 + 29 * p}`).join(' ') + ' Z' : ''
  return (
    <div className="mt-3 space-y-2">
      <audio ref={audio} controls preload="metadata" src={api.musicAudioUrl(folder)} className="h-9 w-full" aria-label="Music track"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onSeeked={() => setT(audio.current?.currentTime ?? 0)} />
      {a && <>
        <div className="relative cursor-pointer select-none overflow-hidden rounded-lg bg-stone-900" onClick={seek} title="click to jump there; thin lines are the bar lines, the brighter one is the first downbeat">
          {wave && <svg viewBox="0 0 1000 60" preserveAspectRatio="none" role="img" aria-label="Waveform of the track" className="block h-14 w-full"><path d={wave} className="fill-emerald-400" /></svg>}
          <img src={api.musicSpectrogramUrl(folder, v)} alt="Spectrogram of the track: pitch up the side, time along" className="block h-24 w-full" draggable={false} />
          <div className="pointer-events-none absolute inset-0">
            {bars.map((x, i) => <div key={i} className={`absolute top-0 h-full ${i === 0 ? 'w-0.5 bg-white/80' : 'w-px bg-white/25'}`} style={{ left: `${x * 100}%` }} />)}
            <div data-testid="playhead" className="absolute top-0 h-full w-0.5 bg-amber-400" style={{ left: `${dur > 0 ? Math.min(100, (t / dur) * 100) : 0}%` }} />
          </div>
        </div>
        <div className="flex justify-between text-xs text-stone-500"><span>{mmss(t)}</span><span>{mmss(dur)}</span></div>
        <div className="flex h-3 w-full overflow-hidden rounded bg-stone-200 dark:bg-stone-800" title="energy of the music, bar by bar: the film cuts faster and uses livelier shots where it is high">
          {a.sections.map(([s, e, en], i) => <div key={i} style={{ width: `${(100 * (e - s)) / a.usable_beats}%`, background: `hsl(150 60% ${75 - 40 * en}%)` }} />)}</div>
      </>}
    </div>
  )
}
