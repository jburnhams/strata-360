import { useEffect, useState } from 'react'
import { api, type ClipDetail } from '../api'
import NoteBox from './NoteBox'
import RedoDialog from './RedoDialog'
import { PanelSkeleton, Skeleton } from './Skeleton'

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900"><h3 className="mb-2 text-sm font-semibold">{title}</h3>{children}</section>
)
const Kv = ({ k, v }: { k: string; v: React.ReactNode }) => v == null || v === '' ? null : <div className="flex justify-between gap-3 py-0.5 text-sm"><span className="text-stone-500">{k}</span><span className="text-right">{v}</span></div>

export default function ClipView({ folder, clip, focus }: { folder: string; clip: string; focus?: number }) {
  const [c, setC] = useState<ClipDetail>()
  const [err, setErr] = useState<string>()
  const [redo, setRedo] = useState(false)
  useEffect(() => { setC(undefined); setErr(undefined); api.clip(folder, clip).then(setC).catch(e => setErr(e.message)) }, [folder, clip])
  useEffect(() => { if (c && focus != null) document.getElementById(`seg-${Math.round(focus * 100)}`)?.scrollIntoView({ block: 'center' }) }, [c, focus])
  if (err) return <p className="text-stone-500">{err}</p>
  if (!c) return <div className="space-y-4"><Skeleton className="aspect-video w-full" /><div className="grid gap-4 md:grid-cols-2"><PanelSkeleton title="When and where" /><PanelSkeleton title="Motion and picture" /></div><PanelSkeleton title="Transcript" rows={4} /></div>
  const utc = String(c.time.start_utc ?? ''), m = c.motion, sc = c.scenes?.summary, id = c.identity
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-stone-200 dark:border-stone-800">
        {c.thumb ? <img key={c.thumb.kind} src={api.thumbUrl(folder, clip, c.thumb.kind)} alt="" className="aspect-video w-full object-cover" /> : <div className="grid aspect-video place-items-center bg-stone-200 text-stone-500 dark:bg-stone-800">the thumbnail stage has not run for this clip yet</div>}
        <div className="flex items-center justify-between bg-white px-4 py-2 text-xs text-stone-500 dark:bg-stone-900"><span>{c.thumb ? `${c.thumb.kind} thumbnail at ${fmt(c.thumb.t_s)}: ${c.thumb.why}` : ''}</span><span className="font-mono">{c.id} · <button className="underline" onClick={() => setRedo(true)}>reprocess…</button></span></div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="When and where">
          <Kv k="Start (UTC)" v={utc.replace('T', ' ').replace('Z', '')} /><Kv k="Length" v={fmt(c.video.source_frames / c.video.nominal_fps)} /><Kv k="Time status" v={String(c.time.utc_status)} />
          <Kv k="Track" v={c.track_text} /><Kv k="Dropped frames" v={c.video.dropped_frames || null} />
        </Card>
        <Card title="Motion and picture">
          <Kv k="Steadiness" v={m?.steady != null ? `${Math.round(Number(m.steady) * 100)}%` : null} /><Kv k="Shake" v={m?.median_shake_dps != null ? `${m.median_shake_dps}°/s` : null} />
          <Kv k="Running cadence" v={m?.cadence_hz ? `${(Number(m.cadence_hz) * 60).toFixed(0)} steps/min` : null} /><Kv k="Turning" v={m?.total_turn_deg != null ? `${Math.round(Number(m.total_turn_deg))}°` : null} />
          <Kv k="Brightness range" v={c.exposure?.mean_lin_range_stops != null ? `${Number(c.exposure.mean_lin_range_stops).toFixed(1)} stops` : null} />
        </Card>
        <Card title="What is in shot">
          <Kv k="People" v={id ? `median ${id.median_people}, up to ${id.max_people}` : null} /><Kv k="You in view" v={id ? `${Math.round(Number(id.me_fraction) * 100)}% of samples` : null} />
          <Kv k="Settings" v={sc ? Object.keys(sc.settings ?? {}).join(', ') : null} /><Kv k="Tags" v={sc?.tags?.slice(0, 8).join(', ')} /><Kv k="Lighting" v={sc ? Object.keys(sc.lighting ?? {}).join(', ') : null} />
          {!sc && <p className="text-sm text-stone-500">Scene tagging has not run for this clip yet.</p>}
        </Card>
        <Card title="Usable moments">
          {c.candidates ? c.candidates.map(x => (
            <div key={x.id} className="flex items-center gap-2 py-0.5 text-sm">
              <span className="w-24 font-mono text-xs text-stone-500">{fmt(x.start_s)}–{fmt(x.end_s)}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"><div className="h-full bg-emerald-600" style={{ width: `${x.quality * 100}%` }} /></div>
              {x.features.speech > 0.5 && <span title="you speak">💬</span>}{x.features.chatter > 0.5 && <span title="other voices">🗣</span>}
            </div>
          )) : <p className="text-sm text-stone-500">Candidates are made once the other stages have finished.</p>}
        </Card>
      </div>
      <Card title="Transcript">
        {c.transcript.length === 0 && <p className="text-sm text-stone-500">No speech recognised.</p>}
        {c.transcript.map((l, i) => (
          <div key={i} id={`seg-${Math.round(l.t0 * 100)}`} className={`py-1 text-sm ${l.flagged ? 'opacity-50' : ''} ${focus != null && Math.abs(l.t0 - focus) < 0.05 ? 'rounded bg-emerald-100 px-1 dark:bg-emerald-950' : ''}`}>
            <span className="mr-2 font-mono text-xs text-stone-500">{fmt(l.t0)}</span>
            {l.who && <span className={`mr-2 rounded-full px-2 text-xs ${l.who === 'wearer' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-stone-200 text-stone-600 dark:bg-stone-800 dark:text-stone-400'}`}>{l.who === 'wearer' ? 'you' : 'other'}</span>}
            {l.lang !== 'en' && <span className="mr-2 rounded-full border border-stone-300 px-2 text-xs dark:border-stone-700">{l.lang}</span>}
            <span>{l.text}</span>{l.text_en && l.text_en !== l.text && <div className="ml-10 text-stone-500">→ {l.text_en}</div>}
          </div>
        ))}
      </Card>
      {redo && <RedoDialog folder={folder} clip={clip} onClose={() => setRedo(false)} />}
      <NoteBox folder={folder} clip={clip} title="Notes for this clip" placeholder="What happened here? Names, places, how it felt, anything to mention or avoid…" />
    </div>
  )
}
