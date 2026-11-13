import { useRef, useState } from 'react'
import { api, type LineKey, VoiceLine } from '../api'
import { usePoll } from '../usePoll'
import { PanelSkeleton } from './Skeleton'

const fitTxt = { ok: 'fits', sped: 'sped up a little to fit', over: 'too long: cut at the next line' } as const

// The script spoken by a voice on this machine, placed on the film timeline: real timings, and a track to hear. Record your own take of any line to replace its synthetic one.
export default function VoiceoverPanel({ folder }: { folder: string }) {
  const st = usePoll(() => api.voiceover(folder), 2500, [folder])
  const [err, setErr] = useState<string>()
  const [rec, setRec] = useState<{ seg: LineKey; mr: MediaRecorder } | null>(null)
  const [eng, setEng] = useState<string>(), [voice, setVoice] = useState<string>(), [rate, setRate] = useState<number>()
  const player = useRef<HTMLAudioElement>(null)
  if (!st) return <PanelSkeleton title="Voice-over audio" rows={3} />
  const engine = st.engines.find(e => e.id === (eng ?? st.state.engine)) ?? st.engines[0]
  const voiceName = voice && engine?.voices.some(v => v.name === voice) ? voice : (eng ? undefined : st.state.voice) ?? engine?.voices[0]?.name
  const t = st.timings, input = 'rounded-surface border border-border bg-card px-2 py-1.5 type-body-sm'
  const build = async () => { setErr(undefined); try { await api.buildVoiceover(folder, { engine: engine?.id, voice: voiceName, rate: rate ?? st.state.rate }) } catch (e) { setErr((e as Error).message) } }
  const play = (url: string) => { const a = player.current; if (a) { a.src = url; void a.play() } }
  const startRec = async (seg: LineKey) => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true }); const mr = new MediaRecorder(s); const parts: Blob[] = []
      mr.ondataavailable = e => parts.push(e.data)
      mr.onstop = async () => { s.getTracks().forEach(x => x.stop()); try { await api.recordVoiceover(folder, seg, new Blob(parts, { type: mr.mimeType })); await api.buildVoiceover(folder) } catch (e) { setErr((e as Error).message) } setRec(null) }
      mr.start(); setRec({ seg, mr })
    } catch { setErr('The browser could not use a microphone (it needs permission, and https or localhost).') }
  }
  const use = async (l: VoiceLine, u: 'synth' | 'recorded') => { await api.voiceoverUse(folder, l.seg, u); await api.buildVoiceover(folder) }
  return (
    <section className="rounded-overlay border border-border bg-card p-4">
      <h3 className="mb-2 type-body-sm font-semibold">Voice-over audio</h3>
      {st.engines.length === 0 ? <p className="type-body-sm text-warning">The voice model is not installed. Run <code>pip install kokoro-onnx</code> and <code>./strata360 voiceover . --fetch</code> (about 350 MB, an open model, runs locally).</p> : (
        <div className="mb-3 flex flex-wrap items-end gap-3 type-body-sm">
          <label>Voice<select value={voiceName} onChange={e => { setVoice(e.target.value); void api.buildVoiceover(folder, { engine: engine?.id, voice: e.target.value, rate: rate ?? st.state.rate }) }} className={`${input} ml-2`}>
            {[...new Set(engine?.voices.map(v => (v as { group?: string }).group ?? ''))].map(g => <optgroup key={g} label={g || 'voices'}>{engine?.voices.filter(v => ((v as { group?: string }).group ?? '') === g).map(v => <option key={v.name} value={v.name}>{st.cached?.some(c => c.voice === v.name && c.rate === st.state.rate) ? '✓ ' : ''}{(v as { label?: string }).label ?? v.name}</option>)}</optgroup>)}</select></label>
          <label>Speed<input type="number" min={100} max={260} value={rate ?? st.state.rate} onChange={e => setRate(Number(e.target.value))} className={`${input} ml-2 w-20`} /></label>
          <button disabled={st.building || !st.lines} onClick={build} className="rounded-surface bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">{st.building ? `Speaking ${st.progress?.done ?? 0}/${st.progress?.total || '…'}` : t ? 'Speak again' : 'Speak the script'}</button>
          {t && <button className="rounded-surface border border-border px-3 py-2" onClick={() => play(api.voiceoverAudio(folder))}>▶ Whole track</button>}
          <audio ref={player} controls className="h-9" />
        </div>
      )}
      {!!st.cached?.length && <div className="mb-2 flex flex-wrap items-center gap-2 type-caption"><span className="text-muted-foreground">Compare (made for this script, ✓ in the list):</span>
        {st.cached.map(c => { const label = (engine?.voices.find(v => v.name === c.voice) as { label?: string } | undefined)?.label ?? c.voice
          return <span key={c.key} className={`inline-flex items-center overflow-hidden rounded-control border ${c.active ? 'border-primary' : 'border-border'}`}>
            <button className="px-1.5 py-0.5 hover:bg-muted" title="play this voice's whole track without switching to it" onClick={() => play(api.voiceoverAudio(folder, undefined, undefined, c.key))}>▶ {label}</button>
            {c.active ? <span className="bg-primary px-1.5 py-0.5 text-primary-foreground">in use</span> : <button className="border-l border-border px-1.5 py-0.5 hover:bg-muted" onClick={() => { setVoice(c.voice); void api.buildVoiceover(folder, { engine: c.engine, voice: c.voice, rate: c.rate }) }}>use</button>}</span> })}</div>}
      {!st.lines && <p className="type-body-sm text-muted-foreground">Write the script first.</p>}
      {!!st.lines && <p className="mb-2 type-caption text-muted-foreground">The script is spoken automatically whenever it is written or an edit is saved; unchanged lines are reused.</p>}
      {(err || st.error) && <p className="mb-2 type-body-sm text-danger">{err || st.error}</p>}
      {t && (
        <div>
          <p className="mb-2 type-body-sm text-muted-foreground">{t.voice} · measured pace {t.measured_wpm} words per minute · {t.over.length ? <span className="text-danger">{t.over.length} line(s) too long</span> : 'every line fits'}{t.sped.length ? ` · ${t.sped.length} sped up slightly` : ''}{t.script !== st.script && <span className="text-warning"> · the script has changed since: speak again</span>}</p>
          <ul className="divide-y divide-border type-body-sm">
            {t.lines.map(l => (
              <li key={l.seg} className="flex flex-wrap items-center gap-3 py-1.5">
                <span className="w-14 shrink-0 font-mono type-caption text-muted-foreground">{Math.floor(l.film_start_s / 60)}:{String(Math.floor(l.film_start_s % 60)).padStart(2, '0')}</span>
                <span className="min-w-0 flex-1">{l.text}</span>
                <span className={`shrink-0 type-caption ${l.fit === 'over' ? 'text-danger' : l.fit === 'sped' ? 'text-warning' : 'text-muted-foreground'}`} title={fitTxt[l.fit]}>{l.natural_s.toFixed(1)}s in {l.room_s.toFixed(1)}s{l.fit === 'over' ? ` (+${l.overrun_s.toFixed(1)})` : ''}</span>
                <span className="flex shrink-0 gap-1 type-caption">
                  <button className={`rounded-control border px-2 py-0.5 ${l.source === 'synth' ? 'border-primary' : 'border-border'}`} onClick={() => play(api.voiceoverAudio(folder, l.seg, 'synth'))} onDoubleClick={() => use(l, 'synth')} title="Play the synthetic line; double-click to use it">▶ voice{l.source === 'synth' ? ' ✓' : ''}</button>
                  {l.has_recording && <button className={`rounded-control border px-2 py-0.5 ${l.source === 'recorded' ? 'border-primary' : 'border-border'}`} onClick={() => play(api.voiceoverAudio(folder, l.seg, 'recorded'))} onDoubleClick={() => use(l, 'recorded')} title="Play your recording; double-click to use it">▶ you{l.source === 'recorded' ? ' ✓' : ''}</button>}
                  {rec?.seg === l.seg ? <button className="rounded-control bg-danger px-2 py-0.5 text-primary-foreground" onClick={() => rec.mr.stop()}>■ stop</button> : <button disabled={!!rec} className="rounded-control border border-border px-2 py-0.5 disabled:opacity-40" onClick={() => startRec(l.seg)}>● record</button>}
                  {l.has_recording && <button className="rounded-control border border-border px-2 py-0.5" onClick={async () => { await api.deleteRecording(folder, l.seg); await api.buildVoiceover(folder) }} title="Remove your recording">✕</button>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
