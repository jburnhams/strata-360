import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type GeneratedPiece, type MusicScore, type ScorePlan, type ScoreSource, type StudioPreset, type StudioPreview, type StudioSettings } from '../api'
import { usePoll } from '../usePoll'

const LEVEL_NAMES = ['sparse', 'steady', 'driving', 'full'], LEVELS = [0.15, 0.4, 0.65, 0.9], PHRASE = 4
const STEMS = ['drums', 'bass', 'other', 'vocals'] as const
const PRESET_NOTES: Record<StudioPreset, string> = { flat: 'steady throughout', arc: 'full at the start and finish, a slow wave between', build: 'rising to the finish', quiet: 'sparse throughout', manual: 'set by hand below', footage: 'follows what is in the film: motion, crowd sound, pace, climb, heart rate and the shots\' own energy; sparser under speech' }
const SIGNAL_LABELS: Record<string, string> = { motion: 'motion', crowd: 'crowd sound', pace: 'pace', climb: 'climb', heart: 'heart rate', technique: 'shot energy' }
// The fidelity slider's five named stops (docs/ai-music.md 4.5): how much of the music is the track's own audio and how much is new material in its style.
export const FIDELITY_STOPS: [number, string, string][] = [[1, 'The record', 'only the track\'s own audio, re-sequenced and layered'], [0.75, 'Extended', 'the track wherever it fits; new bars only for bridges and levels it never reaches'], [0.5, 'Remix', 'about half the bars new, following the intensity'], [0.25, 'Inspired by', 'mostly new, the track as a light reference'], [0, 'In its style', 'all new, from a description of the track']]
export const fidelityName = (f: number) => { const near = FIDELITY_STOPS.reduce((b, s) => (Math.abs(s[0] - f) < Math.abs(b[0] - f) ? s : b)); return Math.abs(near[0] - f) < 0.01 ? near[1] : `between ${FIDELITY_STOPS.filter(s => s[0] > f).pop()?.[1]} and ${FIDELITY_STOPS.find(s => s[0] < f)?.[1]}` }
const nextPin = (p?: ScoreSource): ScoreSource | undefined => (p === undefined ? 'original' : p === 'original' ? 'generate' : undefined)
const mmss = (s: number) => { const r = Math.round(s); return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}` }
const levelIndex = (v: number) => LEVELS.reduce((best, l, i) => (Math.abs(l - v) < Math.abs(LEVELS[best] - v) ? i : best), 0)

// The Music studio: the track's bars and key, a preview of the music built for a length (no audio is made for it: which of the track's bars play where, how intense each phrase is, which layers play), and the built track itself.
// Preview and build use the same settings, so what is shown is what the build will do. The intensity can be set from a preset or by clicking phrases.
export default function MusicStudio({ folder }: { folder: string }) {
  const [tick, setTick] = useState(0)
  const st = usePoll(() => api.musicStudio(folder), 3000, [folder, tick])
  const grid = st?.grid
  const [length, setLength] = useState<number>(), [preset, setPreset] = useState<StudioPreset>('arc'), [manual, setManual] = useState<number[]>(), [windows, setWindows] = useState<[number, number][]>([])
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<string>(), [pv, setPv] = useState<StudioPreview>(), [pvErr, setPvErr] = useState<string>()
  const [fidelity, setFidelity] = useState(0.75), [pins, setPins] = useState<Record<string, ScoreSource>>({}), [style, setStyle] = useState(''), [takes, setTakes] = useState<Record<string, number>>({})
  const seeded = useRef(false), seededScore = useRef(false), footage = st?.footage
  useEffect(() => { if (st && !seededScore.current) { seededScore.current = true; if (st.built?.style) setStyle(st.built.style); if (st.built?.fidelity !== undefined) setFidelity(st.built.fidelity) } }, [st])         // the last build's style and fidelity, once
  useEffect(() => { if (grid && st && !seeded.current) { seeded.current = true; if (footage) { setLength(Math.round(footage.length_s)); setPreset('footage') } else setLength(Math.round(grid.duration_s)) } }, [grid, st, footage])         // the length starts as the film's (or the track's); clearing the box later must not bring it back
  const settings = useMemo<StudioSettings | undefined>(() => length === undefined || !(length >= 4) ? undefined : { length_s: length, preset, ...(preset === 'manual' && manual ? { levels: manual } : {}), windows, fidelity, pins }, [length, preset, manual, windows, fidelity, pins])
  useEffect(() => {
    if (!grid || !settings) return
    let live = true; const t = setTimeout(() => api.previewMusic(folder, settings).then(p => { if (live) { setPv(p); setPvErr(undefined) } }).catch(e => live && setPvErr((e as Error).message)), 250)
    return () => { live = false; clearTimeout(t) }
  }, [folder, grid, settings])
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setMsg(undefined); try { await fn() } catch (e) { setMsg((e as Error).message) } setBusy(false); setTick(t => t + 1) }
  const setLevel = (phrase: number, idx: number) => {
    if (!pv) return
    const lv = [...(preset === 'manual' && manual ? manual : pv.levels)]; for (let i = phrase * PHRASE; i < Math.min(lv.length, (phrase + 1) * PHRASE); i++) lv[i] = LEVELS[idx]
    setManual(lv); setPreset('manual')
  }
  if (!st) return <p className="text-sm text-stone-500">Loading the music studio…</p>
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-base font-semibold">Music studio</h2>
          {grid ? <span className="text-sm text-stone-600 dark:text-stone-400">{grid.bpm} bpm · {grid.key.name} · {grid.bars} bars of {grid.bar_s.toFixed(2)} s · {mmss(grid.duration_s)} long</span> : <span className="text-sm text-stone-500">The track has not been analysed for building yet.</span>}
          <button className="rounded-lg border border-stone-300 px-3 py-1 text-sm disabled:opacity-50 dark:border-stone-700" disabled={busy} onClick={() => run(() => api.analyseMusic(folder))}>{busy ? 'analysing…' : grid ? 'Analyse again' : 'Analyse the track'}</button>
        </div>
        {grid && grid.key.confidence < 0.3 && <p className="mt-1 text-xs text-amber-700">The key is a guess (low confidence).</p>}
        {msg && <p role="alert" className="mt-2 text-sm text-amber-700">{msg}</p>}
        {grid && <BarEnergy energy={grid.energy} used={pv?.plan.bars} />}
      </section>

      {grid && <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
        <h3 className="mb-2 text-sm font-semibold">What to build</h3>
        <div className="flex flex-wrap items-end gap-4 text-sm">
          <label className="flex flex-col gap-1">Length (seconds)<input type="number" min={4} max={3600} value={length ?? ''} onChange={e => setLength(e.target.value === '' ? undefined : Number(e.target.value))} className="w-28 rounded border border-stone-300 px-2 py-1 dark:border-stone-700 dark:bg-stone-950" /></label>
          <label className="flex flex-col gap-1">Intensity over the film
            <select value={preset} onChange={e => setPreset(e.target.value as StudioPreset)} className="rounded border border-stone-300 px-2 py-1 dark:border-stone-700 dark:bg-stone-950">
              {(footage ? ['footage', 'arc', 'flat', 'build', 'quiet'] as StudioPreset[] : ['arc', 'flat', 'build', 'quiet'] as StudioPreset[]).map(p => <option key={p} value={p}>{p === 'footage' ? 'follow the footage' : p}</option>)}{preset === 'manual' && <option value="manual">manual</option>}</select></label>
          <span className="pb-1 text-xs text-stone-500">{PRESET_NOTES[preset]}</span>
        </div>
        <Fidelity fidelity={fidelity} setFidelity={setFidelity} style={style} setStyle={setStyle} generator={!!st.generator} />
        <Windows windows={windows} setWindows={setWindows} max={length ?? 0} />
        <div className="mt-3 flex items-center gap-3">
          <button className="rounded-lg bg-emerald-700 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50" disabled={st.building || busy || !!pvErr || !settings}
            onClick={() => run(async () => { if (!settings) return; const r = await api.buildMusic(folder, { ...settings, style, takes }); if (!r.started) throw new Error(r.reason || 'could not start') })}>{st.building ? 'Building…' : 'Build this music'}</button>
          {st.building && <span className="text-xs text-stone-500">{st.log || 'starting (the first build separates the stems, which takes a few minutes)'}</span>}
          {!st.building && st.error && <span role="alert" className="text-xs text-red-700">The build failed: {st.error}</span>}
        </div>
      </section>}

      {pvErr && <p role="alert" className="text-sm text-amber-700">{pvErr}</p>}
      {pv && <Preview pv={pv} setLevel={setLevel} pins={pins} setPin={(first, p) => { const n = { ...pins }; if (p) n[String(first)] = p; else delete n[String(first)]; setPins(n) }} generator={!!st.generator} style={style} />}

      {st.built && <Built folder={folder} score={st.built} v={`${st.built.length_s}-${st.built.worst_join}-${st.built.bars.join('').length}-${(st.built.generated ?? []).map(p => p.seed).join('')}`} takes={takes} setTakes={setTakes} />}
    </div>
  )
}

function BarEnergy({ energy, used }: { energy: number[]; used?: number[] }) {
  const counts = new Map<number, number>(); used?.forEach(b => counts.set(b, (counts.get(b) ?? 0) + 1))
  return (
    <div className="mt-3">
      <div className="mb-1 text-xs text-stone-500">The track's own bars, by loudness{used ? '; a dot marks each time a bar is used in the build' : ''}</div>
      <div className="flex h-14 items-end gap-px" role="img" aria-label={`Loudness of each of the track's ${energy.length} bars`}>
        {energy.map((e, i) => <div key={i} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`bar ${i + 1}: loudness ${Math.round(e * 100)}%${counts.get(i) ? `, used ${counts.get(i)} time${counts.get(i) === 1 ? '' : 's'}` : ', not used'}`}>
          <div className={`w-full rounded-t-sm ${counts.get(i) || !used ? 'bg-emerald-500' : 'bg-stone-300 dark:bg-stone-700'}`} style={{ height: `${8 + 92 * e}%` }} />
          {used && <div data-testid="uses" className="mt-0.5 h-1 w-full rounded-full bg-amber-400" style={{ opacity: Math.min(1, (counts.get(i) ?? 0) / 4) }} />}
        </div>)}
      </div>
    </div>
  )
}

function Windows({ windows, setWindows, max }: { windows: [number, number][]; setWindows: (w: [number, number][]) => void; max: number }) {
  const set = (i: number, k: 0 | 1, v: number) => setWindows(windows.map((w, j) => (j === i ? (k === 0 ? [v, w[1]] : [w[0], v]) : w) as [number, number]))
  return (
    <div className="mt-3 text-sm">
      <div className="flex flex-wrap items-center gap-2"><span>Moments where the original's singing is let through</span>
        <button className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700" onClick={() => setWindows([...windows, [Math.round(max / 2), Math.min(max, Math.round(max / 2) + 12)]])}>add a moment</button></div>
      {windows.length === 0 && <p className="text-xs text-stone-500">None: the music is instrumental throughout.</p>}
      <ul className="mt-1 space-y-1">{windows.map((w, i) => <li key={i} className="flex items-center gap-2 text-xs">
        <label>from <input aria-label={`Moment ${i + 1} from (seconds)`} type="number" min={0} max={max} value={w[0]} onChange={e => set(i, 0, Number(e.target.value))} className="w-20 rounded border border-stone-300 px-1 py-0.5 dark:border-stone-700 dark:bg-stone-950" /></label>
        <label>to <input aria-label={`Moment ${i + 1} to (seconds)`} type="number" min={0} max={max} value={w[1]} onChange={e => set(i, 1, Number(e.target.value))} className="w-20 rounded border border-stone-300 px-1 py-0.5 dark:border-stone-700 dark:bg-stone-950" /></label> seconds
        <button className="underline" onClick={() => setWindows(windows.filter((_, j) => j !== i))}>remove</button></li>)}</ul>
    </div>
  )
}

// The fidelity slider and the style of the track, which the generated sections' caption names (a caption without the genre gave jazz on Legends).
function Fidelity({ fidelity, setFidelity, style, setStyle, generator }: { fidelity: number; setFidelity: (f: number) => void; style: string; setStyle: (s: string) => void; generator: boolean }) {
  const stop = FIDELITY_STOPS.find(s => Math.abs(s[0] - fidelity) < 0.01)
  return (
    <div className="mt-3 space-y-2 text-sm">
      <label className="flex flex-col gap-1">True to the track, or in its style: <span className="font-medium">{fidelityName(fidelity)}</span>
        <input type="range" min={0} max={1} step={0.05} value={fidelity} onChange={e => setFidelity(Number(e.target.value))} aria-label="Fidelity" className="w-full max-w-md" list="fidelity-stops" />
        <datalist id="fidelity-stops">{FIDELITY_STOPS.map(([v]) => <option key={v} value={v} />)}</datalist></label>
      <div className="flex max-w-md justify-between text-xs text-stone-500">{[...FIDELITY_STOPS].reverse().map(([v, n]) => <button key={v} type="button" className={`underline-offset-2 hover:underline ${Math.abs(v - fidelity) < 0.01 ? 'font-semibold text-stone-800 dark:text-stone-200' : ''}`} onClick={() => setFidelity(v)}>{n}</button>)}</div>
      {stop && <p className="text-xs text-stone-500">{stop[2]}</p>}
      {fidelity < 1 && <label className="flex max-w-xl flex-col gap-1">The track's style, for the new bars (genre and instruments)
        <input value={style} onChange={e => setStyle(e.target.value)} placeholder="e.g. rap rock, heavy distorted guitar riff, punchy live drums" className="rounded border border-stone-300 px-2 py-1 dark:border-stone-700 dark:bg-stone-950" /></label>}
      {fidelity < 1 && !generator && <p className="text-xs text-amber-700">ACE-Step is not installed, so sections marked to generate will play the track's own bars.</p>}
      {fidelity < 1 && generator && !style.trim() && <p className="text-xs text-amber-700">Name the style: without it the new bars stay the track's own.</p>}
    </div>
  )
}

// The score: which sections are the track's own bars and which are new, and where the original is sung. Click a section to pin it to the track or to new bars (click again to unpin).
function Score({ score, bars, barS, pins, setPin, note }: { score: ScorePlan; bars: number; barS: number; pins: Record<string, ScoreSource>; setPin: (first: number, p?: ScoreSource) => void; note?: string }) {
  const gen = score.sections.filter(s => s.source === 'generate'), fresh = gen.filter(s => s.new).length
  return (
    <div>
      <div className="mb-1 text-xs font-medium">Score: {Math.round(score.share_original * 100)}% the track's own bars{gen.length ? `, ${gen.length} section${gen.length === 1 ? '' : 's'} of new bars${fresh ? ` (${fresh} to make)` : ' (all made already)'}` : ''}. Click a section to pin it.</div>
      <div className="relative flex h-8 gap-px" aria-label="Score sections">
        {score.sections.map(s => { const pin = pins[String(s.first)]
          return <button key={s.first} data-source={s.source} style={{ flexGrow: s.end - s.first }} onClick={() => setPin(s.first, nextPin(pin))}
            aria-label={`Bars ${s.first + 1} to ${s.end} (${mmss(s.first * barS)}): ${s.source === 'original' ? "the track's own bars" : 'new bars'}${pin ? `, pinned to ${pin === 'original' ? 'the track' : 'new bars'}` : ''}${s.new ? ', not made yet' : ''}`}
            title={`bars ${s.first + 1} to ${s.end}: ${s.source === 'original' ? 'the track' : `new bars (${s.repaint ? 'repainted inside the track' : 'made fresh'}, reference ${Math.round((s.strength ?? 0) * 100)}%)`}; the track is ${Math.round(s.mismatch * 100)}% away from this level`}
            className={`min-w-0 basis-0 rounded-sm text-[10px] text-white ${s.source === 'original' ? 'bg-emerald-600' : 'bg-violet-600'} ${pin ? 'ring-2 ring-amber-400 ring-inset' : ''} ${s.new && s.source === 'generate' ? 'bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(255,255,255,.2)_4px,rgba(255,255,255,.2)_8px)]' : ''}`}>{pin ? 'pinned' : ''}</button> })}
        {score.sung.map(m => <div key={m.first} data-testid="sung" className="pointer-events-none absolute bottom-0 h-1.5 rounded-full bg-sky-400" style={{ left: `${(m.first / bars) * 100}%`, width: `${((m.end - m.first) / bars) * 100}%` }} title={`sung: ${m.form === 'a' ? "the track's own bars" : 'its vocal over the new accompaniment'}`} />)}
      </div>
      <div className="mt-1 text-xs text-stone-500"><span className="text-emerald-600">●</span> the track <span className="text-violet-600">●</span> new bars <span className="text-sky-500">●</span> sung</div>
      {score.unreachable.length > 0 && <p className="mt-1 text-xs text-amber-700">The track never gets {score.unreachable.length === 1 ? 'this' : 'these'} quiet or loud: bar{score.unreachable.length === 1 ? '' : 's'} {score.unreachable.map(b => b + 1).join(', ')}. The layers do what they can; lower the fidelity to make new bars there.</p>}
      {note && gen.length > 0 && <p className="mt-1 text-xs text-amber-700">{note}</p>}
    </div>
  )
}

function Preview({ pv, setLevel, pins, setPin, generator, style }: { pv: StudioPreview; setLevel: (phrase: number, idx: number) => void; pins: Record<string, ScoreSource>; setPin: (first: number, p?: ScoreSource) => void; generator: boolean; style: string }) {
  const phrases = Math.ceil(pv.bars / PHRASE), worst = pv.plan.joins.length ? Math.max(...pv.plan.joins) : 0
  return (
    <section className="space-y-5 rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900" aria-label="Preview of the build">
      <div className="flex flex-wrap items-baseline gap-3"><h3 className="text-sm font-semibold">Preview</h3><span className="text-xs text-stone-500">{pv.bars} bars · {mmss(pv.length_s)} · {pv.plan.joins.length === 0 ? 'the track played as it is' : <>{pv.plan.runs.length} stretches of the track joined by {pv.plan.joins.length} cut{pv.plan.joins.length === 1 ? '' : 's'}, worst join {Math.round(worst * 100)}%</>}</span></div>

      <div>
        <div className="mb-1 text-xs font-medium">Intensity: click a phrase to change its level</div>
        <div className="flex items-end gap-2"><span className="w-20 shrink-0 text-xs text-stone-500">level</span>
        <div className="flex h-20 flex-1 items-end gap-0.5">
          {Array.from({ length: phrases }, (_, p) => { const idx = levelIndex(pv.levels[p * PHRASE] ?? 0.4)
            return <button key={p} aria-label={`Phrase ${p + 1} (from ${mmss(p * PHRASE * pv.bar_s)}): ${LEVEL_NAMES[idx]}. Click for the next level`} title={`${mmss(p * PHRASE * pv.bar_s)}: ${LEVEL_NAMES[idx]}`} onClick={() => setLevel(p, (idx + 1) % LEVELS.length)}
              className="flex h-full min-w-0 flex-1 items-end rounded-sm bg-stone-100 hover:bg-stone-200 dark:bg-stone-800 dark:hover:bg-stone-700"><span className="block w-full rounded-sm bg-emerald-600" style={{ height: `${20 + 26.7 * idx}%` }} /></button> })}
        </div></div>
        <div className="mt-1 flex justify-between pl-[5.5rem] text-xs text-stone-500"><span>0:00</span><span>{LEVEL_NAMES.join(' · ')}</span><span>{mmss(pv.length_s)}</span></div>
        {pv.why && <Why why={pv.why} />}
      </div>

      {pv.score && <Score score={pv.score} bars={pv.bars} barS={pv.bar_s} pins={pins} setPin={setPin} note={!generator ? 'Without ACE-Step these play the track\'s own bars.' : !style.trim() ? 'Without a style these play the track\'s own bars.' : undefined} />}

      <div>
        <div className="mb-1 text-xs font-medium">Layers: which parts of the track play, bar by bar</div>
        <div className="space-y-0.5">{STEMS.map(n => <div key={n} className="flex items-center gap-2"><span className="w-20 shrink-0 text-xs text-stone-500">{n}</span>
          <div className="flex h-4 flex-1 gap-px" role="img" aria-label={`${n} layer by bar`}>{pv.gains[n].map((g, i) => <div key={i} data-stem={n} className={`min-w-0 flex-1 ${n === 'vocals' ? 'bg-sky-500' : 'bg-emerald-600'}`} style={{ opacity: 0.08 + 0.92 * g }} />)}</div></div>)}</div>
        {pv.windows.length > 0 && <p className="mt-1 text-xs text-sky-700 dark:text-sky-400">The original's singing plays in bars {pv.windows.map(([a, b]) => `${a + 1} to ${b}`).join(' and ')}.</p>}
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <PathPlot pv={pv} />
        <Similarity pv={pv} />
      </div>
    </section>
  )
}

// What the 'follow the footage' curve was made from: each signal's value per bar (darker: more), and the bars where speech keeps the music down.
function Why({ why }: { why: NonNullable<StudioPreview['why']> }) {
  return (
    <div className="mt-2 space-y-0.5" aria-label="What drove the intensity">
      {why.signals.map(s => <div key={s.name} className="flex items-center gap-2"><span className="w-20 shrink-0 text-xs text-stone-500" title={`weight ${s.weight}`}>{SIGNAL_LABELS[s.name] ?? s.name}</span>
        <div className="flex h-3 flex-1 gap-px" role="img" aria-label={`${SIGNAL_LABELS[s.name] ?? s.name} by bar`}>{s.values.map((v, i) => <div key={i} data-signal={s.name} className="min-w-0 flex-1 bg-amber-500" style={{ opacity: 0.08 + 0.92 * v }} />)}</div></div>)}
      {why.speech.some(Boolean) && <div className="flex items-center gap-2"><span className="w-20 shrink-0 text-xs text-stone-500">speech</span>
        <div className="flex h-3 flex-1 gap-px" role="img" aria-label="speech by bar">{why.speech.map((v, i) => <div key={i} data-signal="speech" className={`min-w-0 flex-1 ${v ? 'bg-sky-500' : 'bg-transparent'}`} />)}</div></div>}
    </div>
  )
}

const costColour = (c: number) => (c < 0.1 ? '#10b981' : c < 0.25 ? '#f59e0b' : '#ef4444')

// Film bar along the bottom, the track's bar up the side: a diagonal is the track playing on, a jump is a cut to another stretch (green: a join that sounds alike, red: a rough one).
function PathPlot({ pv }: { pv: StudioPreview }) {
  const n = Math.max(...pv.plan.bars, 1) + 1, T = pv.bars; let x = 0
  return (
    <div>
      <div className="mb-1 text-xs font-medium">Which of the track's bars play where</div>
      <svg viewBox={`0 0 ${T} ${n}`} preserveAspectRatio="none" role="img" aria-label="The film's bars against the track's bars" className="h-48 w-full rounded bg-stone-100 dark:bg-stone-800">
        {pv.plan.runs.map(([a, len], i) => { const x0 = x; x += len; return <g key={i}>
          <line data-testid="run" x1={x0} y1={n - a} x2={x0 + len} y2={n - a - len} stroke="#059669" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
          {i > 0 && <line data-testid="join" x1={x0} y1={n - (pv.plan.runs[i - 1][0] + pv.plan.runs[i - 1][1])} x2={x0} y2={n - a} stroke={costColour(pv.plan.joins[i - 1] ?? 0)} strokeWidth={1.2} vectorEffect="non-scaling-stroke"><title>{`join ${i}: ${Math.round((pv.plan.joins[i - 1] ?? 0) * 100)}% unlike`}</title></line>}</g> })}
      </svg>
      <div className="mt-1 flex justify-between text-xs text-stone-500"><span>film start</span><span><span className="text-emerald-600">●</span> alike <span className="text-amber-500">●</span> so-so <span className="text-red-500">●</span> rough</span><span>film end</span></div>
    </div>
  )
}

// How alike each pair of the track's bars sounds (bright: alike). The stretches the build plays are outlined along the diagonal.
function Similarity({ pv }: { pv: StudioPreview }) {
  const n = pv.sim.length
  return (
    <div>
      <div className="mb-1 text-xs font-medium">How alike the track's bars sound</div>
      <svg viewBox={`0 0 ${n} ${n}`} role="img" aria-label="Similarity of the track's bars" shapeRendering="crispEdges" className="aspect-square h-48 w-48 rounded bg-stone-900">
        {pv.sim.flatMap((row, i) => row.map((v, j) => v >= 0.6 ? <rect key={`${i}-${j}`} x={j} y={i} width={1} height={1} fill="#34d399" opacity={(v - 0.6) / 0.4} /> : null))}
        {pv.plan.runs.map(([a, len], i) => <rect key={`r${i}`} data-testid="stretch" x={a} y={a} width={len} height={len} fill="none" stroke="#fbbf24" strokeWidth={0.6} vectorEffect="non-scaling-stroke" />)}
      </svg>
    </div>
  )
}

function Built({ folder, score, v, takes, setTakes }: { folder: string; score: MusicScore; v: string; takes: Record<string, number>; setTakes: (t: Record<string, number>) => void }) {
  const leak = score.stray_vocal_db, ck = score.check, gen = score.generated ?? []
  return (
    <section className="rounded-xl border border-emerald-600 bg-white p-4 dark:bg-stone-900" aria-label="The built music">
      <div className="flex flex-wrap items-baseline gap-3"><h3 className="text-sm font-semibold">Built music</h3>
        <span className="text-sm text-stone-600 dark:text-stone-400">{mmss(score.length_s)} · {score.bpm} bpm · {score.key.name} · {score.bars.length} bars in {score.runs.length} stretches · worst join {Math.round(score.worst_join * 100)}%{score.fidelity !== undefined ? ` · ${fidelityName(score.fidelity)}` : ''}</span></div>
      <audio controls preload="metadata" src={api.builtMusicUrl(folder, v)} className="mt-2 h-9 w-full" aria-label="Built music" />
      <p className="mt-1 text-xs text-stone-500">{score.windows.length ? `The original's singing plays in ${score.windows.length} moment${score.windows.length === 1 ? '' : 's'}. ` : 'Instrumental throughout. '}{leak === null ? 'No singing outside them.' : `Singing outside them is ${Math.abs(leak)} dB below the loudest (the gain ramp at the edge of a moment).`}</p>
      {ck && <Checks ck={ck} />}
      {gen.length > 0 && <div className="mt-3">
        <div className="mb-1 text-xs font-medium">New bars</div>
        <ul className="space-y-2">{gen.map(p => <Piece key={`${p.first}-${p.key}`} p={p} chosen={p.key ? takes[p.key] : undefined} choose={seed => { if (!p.key) return; const t = { ...takes }; if (seed === undefined) delete t[p.key]; else t[p.key] = seed; setTakes(t) }} />)}</ul>
        {Object.keys(takes).length > 0 && <p className="mt-1 text-xs text-sky-700 dark:text-sky-400">Build again to use the takes chosen.</p>}
      </div>}
    </section>
  )
}

// G5's checks of the built track: its downbeats against the track's grid, its length against the film, and no singing where there should be none.
function Checks({ ck }: { ck: NonNullable<MusicScore['check']> }) {
  const row = (ok: boolean | null | undefined, text: string) => <li className={ok === false ? 'text-red-700' : ok === null || ok === undefined ? 'text-stone-500' : 'text-emerald-700 dark:text-emerald-400'}>{ok === false ? '✗' : ok ? '✓' : '–'} {text}</li>
  const g = ck.grid, l = ck.length
  return (
    <ul className="mt-2 space-y-0.5 text-xs" aria-label="Checks">
      {row(g.ok, g.ok === null ? `Beat check not run: ${g.why}` : `Downbeats on the track's grid: worst ${g.worst_ms} ms, typical ${g.median_ms} ms${g.off_bars?.length ? `; bars ${g.off_bars.map(b => b + 1).join(', ')} are more than 40 ms off` : ''}`)}
      {row(l.ok, `Length ${mmss(l.length_s)}${l.trimmed_s ? `, ${l.trimmed_s} s cut${l.faded ? ' with a fade' : ''}` : ''}${l.padded_s ? `, ${l.padded_s} s of silence at the end` : ''}`)}
      {row(ck.stray_vocal_db === null || ck.stray_vocal_db < -30, ck.stray_vocal_db === null ? 'No singing outside the sung moments' : `Singing outside the sung moments at ${ck.stray_vocal_db} dB`)}
      {ck.singing_in_generated.length > 0 && row(false, `Singing heard in the new bars from bar ${ck.singing_in_generated.map(b => b + 1).join(', ')}`)}
      {ck.failed.length > 0 && row(false, `New bars not made from bar ${ck.failed.map(b => b + 1).join(', ')}: the track's own bars play there`)}
    </ul>
  )
}

const VERDICT: Record<string, string> = { 'as is': 'in time', stretched: 'stretched to time', repaint: 'off the beat', regenerate: 'wrong tempo', failed: 'not made' }

// One stretch of new bars: how it was made and its takes. Pick a take that kept time, or ask for another one; either is used at the next build.
function Piece({ p, chosen, choose }: { p: GeneratedPiece; chosen?: number; choose: (seed?: number) => void }) {
  const all = p.all_takes ?? p.takes ?? [], good = all.filter(t => t.action === 'as is' || t.action === 'stretched'), next = Math.max(-1, ...all.map(t => t.seed), chosen ?? -1) + 1
  return (
    <li className="rounded border border-stone-200 p-2 text-xs dark:border-stone-800">
      <div className="flex flex-wrap items-baseline gap-2"><span className="font-medium">Bars {p.first + 1} to {p.end}</span>
        {p.kept_original ? <span className="text-amber-700">the track's own bars: {p.why}</span> : <span className="text-stone-500">{p.mode === 'repaint' ? 'repainted inside the track' : p.mode === 'cover' ? 'a cover of these bars' : 'made from the style alone'} · take {p.seed}{p.gain ? ` · level ×${p.gain}` : ''}{p.singing_db != null ? ` · vocals ${p.singing_db} dB` : ''}</span>}</div>
      {p.key && <div className="mt-1 flex flex-wrap items-center gap-2">
        {all.map(t => { const ok = t.action === 'as is' || t.action === 'stretched'
          return <label key={t.seed} className={`flex items-center gap-1 ${ok ? '' : 'text-stone-400'}`} title={t.why ?? ''}><input type="radio" name={`take-${p.key}`} disabled={!ok} checked={chosen === undefined ? t.seed === p.seed : chosen === t.seed} onChange={() => choose(t.seed === p.seed && chosen === undefined ? undefined : t.seed)} />take {t.seed}: {VERDICT[t.action] ?? t.action}</label> })}
        <button type="button" className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-700" onClick={() => choose(next)}>{chosen !== undefined && !all.some(t => t.seed === chosen) ? `take ${chosen} at the next build` : 'another take'}</button>
        {chosen !== undefined && <button type="button" className="underline" onClick={() => choose(undefined)}>back to the first good take</button>}
        {good.length === 0 && all.length > 0 && <span className="text-amber-700">no take kept time yet</span>}
      </div>}
    </li>
  )
}
