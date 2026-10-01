import { useRef, useState } from 'react'
import { api, VoiceLine } from '../api'
import { usePoll } from '../usePoll'
import { PanelSkeleton } from './Skeleton'

const fitTxt = { ok: 'fits', sped: 'sped up a little to fit', over: 'too long: cut at the next line' } as const

// The script spoken by a voice on this machine, placed on the film timeline: real timings, and a track to hear. Record your own take of any line to replace its synthetic one.
export default function VoiceoverPanel({ folder }: { folder: string }) {
  const st = usePoll(() => api.voiceover(folder), 2500, [folder])
  const [err, setErr] = useState<string>()
  const [rec, setRec] = useState<{ seg: number; mr: MediaRecorder } | null>(null)
  const [eng, setEng] = useState<string>(), [voice, setVoice] = useState<string>(), [rate, setRate] = useState<number>()
  const player = useRef<HTMLAudioElement>(null)
  if (!st) return <PanelSkeleton title="Voice-over audio" rows={3} />
  const engine = st.engines.find(e => e.id === (eng ?? st.state.engine)) ?? st.engines[0]
  const voiceName = voice && engine?.voices.some(v => v.name === voice) ? voice : (eng ? undefined : st.state.voice) ?? engine?.voices[0]?.name
  const t = st.timings, input = 'rounded-lg border border-stone-300 bg-stone-50 px-2 py-1.5 text-sm dark:border-stone-700 dark:bg-stone-950'
  const build = async () => { setErr(undefined); try { await api.buildVoiceover(folder, { engine: engine?.id, voice: voiceName, rate: rate ?? st.state.rate }) } catch (e) { setErr((e as Error).message) } }
  const play = (url: string) => { const a = player.current; if (a) { a.src = url; void a.play() } }
  const startRec = async (seg: number) => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true }); const mr = new MediaRecorder(s); const parts: Blob[] = []
      mr.ondataavailable = e => parts.push(e.data)
      mr.onstop = async () => { s.getTracks().forEach(x => x.stop()); try { await api.recordVoiceover(folder, seg, new Blob(parts, { type: mr.mimeType })); await api.buildVoiceover(folder) } catch (e) { setErr((e as Error).message) } setRec(null) }
      mr.start(); setRec({ seg, mr })
    } catch { setErr('The browser could not use a microphone (it needs permission, and https or localhost).') }
  }
  const use = async (l: VoiceLine, u: 'synth' | 'recorded') => { await api.voiceoverUse(folder, l.seg, u); await api.buildVoiceover(folder) }
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <h3 className="mb-2 text-sm font-semibold">Voice-over audio</h3>
      {st.engines.length === 0 ? <p className="text-sm text-amber-700">The voice model is not installed. Run <code>pip install kokoro-onnx</code> and <code>./strata360 voiceover . --fetch</code> (about 350 MB, an open model, runs locally).</p> : (
        <div className="mb-3 flex flex-wrap items-end gap-3 text-sm">
          <label>Voice<select value={voiceName} onChange={e => { setVoice(e.target.value); void api.buildVoiceover(folder, { engine: engine?.id, voice: e.target.value, rate: rate ?? st.state.rate }) }} className={`${input} ml-2`}>
            {[...new Set(engine?.voices.map(v => (v as { group?: string }).group ?? ''))].map(g => <optgroup key={g} label={g || 'voices'}>{engine?.voices.filter(v => ((v as { group?: string }).group ?? '') === g).map(v => <option key={v.name} value={v.name}>{(v as { label?: string }).label ?? v.name}</option>)}</optgroup>)}</select></label>
          <label>Speed<input type="number" min={100} max={260} value={rate ?? st.state.rate} onChange={e => setRate(Number(e.target.value))} className={`${input} ml-2 w-20`} /></label>
          <button disabled={st.building || !st.lines} onClick={build} className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-50">{st.building ? `Speaking ${st.progress?.done ?? 0}/${st.progress?.total || '…'}` : t ? 'Speak again' : 'Speak the script'}</button>
          {t && <button className="rounded-lg border border-stone-300 px-3 py-2 dark:border-stone-700" onClick={() => play(api.voiceoverAudio(folder))}>▶ Whole track</button>}
          <audio ref={player} controls className="h-9" />
        </div>
      )}
      {!st.lines && <p className="text-sm text-stone-500">Write the script first.</p>}
      {!!st.lines && <p className="mb-2 text-xs text-stone-500">The script is spoken automatically whenever it is written or an edit is saved; unchanged lines are reused.</p>}
      {(err || st.error) && <p className="mb-2 text-sm text-red-600">{err || st.error}</p>}
      {t && (
        <div>
          <p className="mb-2 text-sm text-stone-500">{t.voice} · measured pace {t.measured_wpm} words per minute · {t.over.length ? <span className="text-red-600">{t.over.length} line(s) too long</span> : 'every line fits'}{t.sped.length ? ` · ${t.sped.length} sped up slightly` : ''}{t.script !== st.script && <span className="text-amber-700"> · the script has changed since: speak again</span>}</p>
          <ul className="divide-y divide-stone-200 text-sm dark:divide-stone-800">
            {t.lines.map(l => (
              <li key={l.seg} className="flex flex-wrap items-center gap-3 py-1.5">
                <span className="w-14 shrink-0 font-mono text-xs text-stone-500">{Math.floor(l.film_start_s / 60)}:{String(Math.floor(l.film_start_s % 60)).padStart(2, '0')}</span>
                <span className="min-w-0 flex-1">{l.text}</span>
                <span className={`shrink-0 text-xs ${l.fit === 'over' ? 'text-red-600' : l.fit === 'sped' ? 'text-amber-700' : 'text-stone-500'}`} title={fitTxt[l.fit]}>{l.natural_s.toFixed(1)}s in {l.room_s.toFixed(1)}s{l.fit === 'over' ? ` (+${l.overrun_s.toFixed(1)})` : ''}</span>
                <span className="flex shrink-0 gap-1 text-xs">
                  <button className={`rounded border px-2 py-0.5 ${l.source === 'synth' ? 'border-emerald-600' : 'border-stone-300 dark:border-stone-700'}`} onClick={() => play(api.voiceoverAudio(folder, l.seg, 'synth'))} onDoubleClick={() => use(l, 'synth')} title="Play the synthetic line; double-click to use it">▶ voice{l.source === 'synth' ? ' ✓' : ''}</button>
                  {l.has_recording && <button className={`rounded border px-2 py-0.5 ${l.source === 'recorded' ? 'border-emerald-600' : 'border-stone-300 dark:border-stone-700'}`} onClick={() => play(api.voiceoverAudio(folder, l.seg, 'recorded'))} onDoubleClick={() => use(l, 'recorded')} title="Play your recording; double-click to use it">▶ you{l.source === 'recorded' ? ' ✓' : ''}</button>}
                  {rec?.seg === l.seg ? <button className="rounded bg-red-600 px-2 py-0.5 text-white" onClick={() => rec.mr.stop()}>■ stop</button> : <button disabled={!!rec} className="rounded border border-stone-300 px-2 py-0.5 disabled:opacity-40 dark:border-stone-700" onClick={() => startRec(l.seg)}>● record</button>}
                  {l.has_recording && <button className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-700" onClick={async () => { await api.deleteRecording(folder, l.seg); await api.buildVoiceover(folder) }} title="Remove your recording">✕</button>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
