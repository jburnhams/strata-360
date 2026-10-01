import { useMemo, useState } from 'react'
import { api, type ClipInfo, type Meta, type Seg } from '../api'
import { usePoll } from '../usePoll'
import { PanelSkeleton } from './Skeleton'
import Phrase, { type Mode } from './Phrase'

const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The whole race as one running transcript: phrases grouped by clip in time order. Hover a phrase for the clip's details (picture, real time, who spoke); click to open the clip at that moment.
export default function TranscriptPanel({ folder, clips, tz, onOpen }: { folder: string; clips: ClipInfo[]; tz: string; onOpen: (clip: string, t: number) => void }) {
  const [ver, setVer] = useState(0)
  const data = usePoll(() => api.transcript(folder), 30000, [folder, ver])
  const fix = usePoll(() => api.transcriptFix(folder), 3000, [folder, ver])
  const [fixErr, setFixErr] = useState<string>()
  const running = fix?.state === 'running'
  const [filter, setFilter] = useState<'all' | 'you'>('all')
  const [mode, setMode] = useState<Mode>('translated')
  const [tip, setTip] = useState<{ seg: Seg; x: number; y: number }>()
  const info = useMemo(() => Object.fromEntries(clips.map(c => [c.id, c])), [clips])
  const groups = useMemo(() => {
    const g: { clip: string; segs: Seg[] }[] = []
    for (const s of data?.segments ?? []) {
      if (filter === 'you' && s.who !== 'wearer') continue
      const last = g[g.length - 1]; if (last && last.clip === s.clip) last.segs.push(s); else g.push({ clip: s.clip, segs: [s] })
    }
    return g
  }, [data, filter])
  if (!data) return <PanelSkeleton title="Transcript" rows={6} />
  const at = (s: Seg) => { const c = info[s.clip]; if (!c) return null; const t = new Date(new Date(c.start_utc).getTime() + s.t0 * 1000); return t }
  const local = (d: Date | null) => d ? d.toLocaleString('en-GB', { timeZone: tz, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-3 flex items-center justify-between text-sm">
        <b>Transcript of everything</b>
        <span className="flex items-center gap-2 text-xs text-stone-500">
          <button disabled={running} title="sends the words (and your notes) to Gemini, which suggests substitutions for obvious recognition errors; they show highlighted and you can change any of them" className="rounded border border-stone-300 px-2 py-0.5 text-stone-700 disabled:opacity-50 dark:border-stone-700 dark:text-stone-300"
            onClick={async () => { setFixErr(undefined); try { await api.suggestTranscript(folder) } catch (e) { setFixErr((e as Error).message) } setVer(v => v + 1) }}>{running ? `asking Gemini… ${fix?.done ?? 0}/${fix?.total ?? '…'}` : 'suggest corrections (Gemini)'}</button>
          {fix?.state === 'done' && <span>{fix.fixes} suggested</span>}{fix?.state === 'error' && <span className="text-red-600">{fix.error}</span>}{fixErr && <span className="text-red-600">{fixErr}</span>}
          <span><span className="rounded bg-amber-200 px-1 dark:bg-amber-500/30">Gemini</span> <span className="rounded bg-sky-200 px-1 dark:bg-sky-500/30">you</span> hover for the original, click a word to edit</span></span>
        <span className="flex items-center gap-3 text-stone-500">{data.segments.length} phrases
          <select value={mode} onChange={e => setMode(e.target.value as Mode)} title="how phrases in other languages are shown" className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
            <option value="translated">translated</option><option value="original">original language</option><option value="both">both</option></select>
          <select value={filter} onChange={e => setFilter(e.target.value as 'all' | 'you')} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
            <option value="all">everyone</option><option value="you">only you</option></select></span>
      </div>
      {groups.length === 0 && <p className="text-sm text-stone-500">{filter === 'you' ? 'No phrases labelled as you yet (voices are labelled by the speakers stage).' : 'No speech recognised yet.'}</p>}
      <div className="space-y-3 text-sm leading-relaxed">
        {groups.map((g, gi) => (
          <div key={gi}>
            <button className="mb-0.5 font-mono text-xs text-stone-500 hover:underline" onClick={() => onOpen(g.clip, g.segs[0].t0)}>{short(g.clip)}{info[g.clip] ? ` · ${Math.round(info[g.clip].duration_s)} s` : ''}</button>
            <p>
              {g.segs.map((s, i) => (
                <span key={i} onMouseEnter={e => setTip({ seg: s, x: e.clientX, y: e.clientY })} onMouseMove={e => setTip({ seg: s, x: e.clientX, y: e.clientY })} onMouseLeave={() => setTip(undefined)}
                  className={`mr-1 rounded px-0.5 hover:bg-emerald-100 dark:hover:bg-emerald-950 ${s.who === 'wearer' ? 'font-medium' : ''} ${s.flagged ? 'italic opacity-50' : ''}`}>
                  <Phrase text={s.text} en={s.text_en} lang={s.lang} mode={mode} className={`cursor-pointer ${s.lang === 'en' ? (s.who === 'wearer' ? 'text-stone-900 dark:text-stone-100' : 'text-stone-500') : ''}`} onText={() => onOpen(s.clip, s.t0)} word={s.words?.length ? { folder, clip: s.clip, si: s.si, words: s.words, onSaved: () => setVer(v => v + 1) } : undefined} />
                </span>
              ))}
            </p>
          </div>
        ))}
      </div>
      {tip && (() => { const c = info[tip.seg.clip], t = at(tip.seg); const left = Math.min(tip.x + 16, window.innerWidth - 300), top = Math.min(tip.y + 16, window.innerHeight - 260); return (
        <div className="pointer-events-none fixed z-40 w-72 overflow-hidden rounded-lg border border-stone-300 bg-white text-xs shadow-lg dark:border-stone-700 dark:bg-stone-900" style={{ left, top }}>
          {c?.thumb && <img src={api.thumbUrl(folder, tip.seg.clip, c.thumb)} alt="" className="aspect-video w-full object-cover" />}
          <div className="space-y-0.5 p-2">
            <div className="font-mono text-stone-500">{tip.seg.clip}</div>
            <div>{local(t)} <span className="text-stone-500">({t ? t.toISOString().slice(11, 19) : ''} UTC)</span></div>
            <div className="text-stone-500">at {mmss(tip.seg.t0)} of {c ? mmss(c.duration_s) : '?'} · {tip.seg.who === 'wearer' ? 'you' : tip.seg.who === 'other' ? 'someone else' : 'voice not labelled yet'} · {tip.seg.lang}</div>
            {c?.steady != null && <div className="text-stone-500">steadiness {Math.round(c.steady * 100)}%{c.candidates != null ? ` · ${c.candidates} usable moments` : ''}</div>}
            {tip.seg.lang !== 'en' && tip.seg.text_en && tip.seg.text_en !== tip.seg.text && <div><span className="text-amber-700 dark:text-amber-300">{tip.seg.text}</span><br /><span className="text-sky-700 dark:text-sky-300">→ {tip.seg.text_en}</span></div>}
            <div className="text-emerald-700 dark:text-emerald-400">click to open this clip</div>
          </div>
        </div>) })()}
    </section>
  )
}
