import { useMemo, useState } from 'react'
import { api, type ClipInfo, type Meta, type Seg } from '../api'
import { usePoll } from '../usePoll'
import { PanelSkeleton } from './Skeleton'

const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The whole race as one running transcript: phrases grouped by clip in time order. Hover a phrase for the clip's details (picture, real time, who spoke); click to open the clip at that moment.
export default function TranscriptPanel({ folder, clips, tz, onOpen }: { folder: string; clips: ClipInfo[]; tz: string; onOpen: (clip: string, t: number) => void }) {
  const data = usePoll(() => api.transcript(folder), 30000, [folder])
  const [filter, setFilter] = useState<'all' | 'you'>('all')
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
        <span className="flex items-center gap-3 text-stone-500">{data.segments.length} phrases
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
                <span key={i} onClick={() => onOpen(s.clip, s.t0)} onMouseEnter={e => setTip({ seg: s, x: e.clientX, y: e.clientY })} onMouseMove={e => setTip({ seg: s, x: e.clientX, y: e.clientY })} onMouseLeave={() => setTip(undefined)}
                  className={`mr-1 cursor-pointer rounded px-0.5 hover:bg-emerald-100 dark:hover:bg-emerald-950 ${s.who === 'wearer' ? 'text-stone-900 dark:text-stone-100' : 'text-stone-500'} ${s.flagged ? 'italic opacity-50' : ''}`}>
                  {s.text}{s.lang !== 'en' && s.text_en && s.text_en !== s.text ? <span className="text-stone-400"> [{s.text_en}]</span> : null}
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
            {tip.seg.text_en && tip.seg.text_en !== tip.seg.text && <div>→ {tip.seg.text_en}</div>}
            <div className="text-emerald-700 dark:text-emerald-400">click to open this clip</div>
          </div>
        </div>) })()}
    </section>
  )
}
