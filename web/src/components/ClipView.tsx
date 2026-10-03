import { useEffect, useMemo, useState } from 'react'
import { api, type ClipDetail, type Photo } from '../api'
import PhotoStrip from './PhotoStrip'
import NoteBox from './NoteBox'
import RedoDialog from './RedoDialog'
import Phrase, { type Mode } from './Phrase'
import PlayIcons from './PlayIcons'
import Moments from './Moments'
import ClipPlayer from './ClipPlayer'
import { PanelSkeleton, Skeleton } from './Skeleton'
import WordMarker from './WordMarker'
import { usedSet } from '../marks'
import { usePoll } from '../usePoll'

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900"><h3 className="mb-2 text-sm font-semibold">{title}</h3>{children}</section>
)
const Kv = ({ k, v }: { k: string; v: React.ReactNode }) => v == null || v === '' ? null : <div className="flex justify-between gap-3 py-0.5 text-sm"><span className="text-stone-500">{k}</span><span className="text-right">{v}</span></div>

export default function ClipView({ folder, clip, focus, photos, tz = 'Europe/Brussels' }: { folder: string; clip: string; focus?: number; photos?: Photo[]; tz?: string }) {
  const [c, setC] = useState<ClipDetail>()
  const [err, setErr] = useState<string>()
  const [redo, setRedo] = useState(false)
  const [mode, setMode] = useState<Mode>('translated')
  const script = usePoll(() => api.script2(folder), 15000, [folder, clip])
  const used = useMemo(() => usedSet(script?.used), [script])
  useEffect(() => { setC(undefined); setErr(undefined); api.clip(folder, clip).then(setC).catch(e => setErr(e.message)) }, [folder, clip])
  const reload = () => api.clip(folder, clip).then(setC).catch(() => {})
  useEffect(() => { if (c && focus != null) document.getElementById(`seg-${Math.round(focus * 100)}`)?.scrollIntoView({ block: 'center' }) }, [c, focus])
  if (err) return <p className="text-stone-500">{err}</p>
  if (!c) return <div className="space-y-4"><Skeleton className="aspect-video w-full" /><div className="grid gap-4 md:grid-cols-2"><PanelSkeleton title="When and where" /><PanelSkeleton title="Motion and picture" /></div><PanelSkeleton title="Transcript" rows={4} /></div>
  const utc = String(c.time.start_utc ?? ''), m = c.motion, sc = c.scenes?.summary, id = c.identity
  return (
    <div className="space-y-4">
      <ClipPlayer folder={folder} clip={clip} thumbKind={c.thumb?.kind} heading={c.heading} focus={c.focus} person={c.person} clarity={c.clarity} scenic={c.scenic} sounds={c.audio_files} hasPreview={!!c.preview} duration={c.video.source_frames / c.video.nominal_fps} />
      <div className="-mt-2 flex items-center justify-between px-1 text-xs text-stone-500"><span>{c.thumb ? `${c.thumb.kind} thumbnail at ${fmt(c.thumb.t_s)}: ${c.thumb.why}` : 'no thumbnail yet'}</span><span className="font-mono">{c.id} · <button className="underline" onClick={() => setRedo(true)}>reprocess…</button></span></div>
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
        <Card title="Where (OpenStreetMap)">
          {!c.places ? <p className="text-sm text-stone-500">The places lookup has not run for this clip yet.</p>
            : !c.places.covered ? <p className="text-sm text-stone-500">{c.places.note}</p>
            : (() => {
              const pts = c.places.points, first = pts[0], last = pts[pts.length - 1]
              const near = new Map<string, { name: string; kind: string; d: number }>()
              pts.forEach(p => (p.nearby ?? []).forEach(n => { const o = near.get(n.name); if (!o || n.distance_m < o.d) near.set(n.name, { name: n.name, kind: n.kind, d: n.distance_m }) }))
              const list = [...near.values()].sort((a, b) => a.d - b.d).slice(0, 8)
              return (<>
                <div className="text-sm font-medium">{c.places.summary?.text}</div>
                <div className="text-xs text-stone-500">{first.address?.road ?? first.address?.display_name}{last.address?.road && last.address.road !== first.address?.road ? ` → ${last.address.road}` : ''}</div>
                <ul className="mt-2 space-y-0.5 text-sm">{list.map(n => <li key={n.name} className="flex justify-between gap-2"><span>{n.name} <span className="text-xs text-stone-500">{n.kind.split('=')[1]}</span></span><span className="text-xs text-stone-500">{n.d} m</span></li>)}</ul>
                <a className="mt-2 inline-block text-xs text-emerald-700 underline dark:text-emerald-400" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/?mlat=${first.lat}&mlon=${first.lon}#map=16/${first.lat}/${first.lon}`}>open in OpenStreetMap</a>
              </>)
            })()}
        </Card>
        <Card title="Usable and unusable moments">
          <Moments duration={c.video.source_frames / c.video.nominal_fps} usable={c.candidates} unusable={c.unusable} thresholds={c.thresholds} />
        </Card>
      </div>
      {c.sounds && <Card title="Sounds">
        <div className="mb-2 flex flex-wrap gap-1.5 text-xs">{Object.entries(c.sounds.seconds).map(([k, v]) => {
          const h = c.sounds!.hints[k]; return <span key={k} title={h ? `${h[0]}: suggested level ${h[1]} dB` : ''} className={`rounded-full border px-2 py-0.5 ${h?.[0] === 'avoid' ? 'border-red-300 text-red-700 dark:text-red-300' : h?.[0] === 'voice' ? 'border-emerald-500 text-emerald-700 dark:text-emerald-300' : 'border-stone-300 text-stone-600 dark:border-stone-600 dark:text-stone-300'}`}>{k} {Math.round(v)} s</span> })}</div>
        <div className="flex h-4 w-full overflow-hidden rounded bg-stone-200 dark:bg-stone-800" title="the strongest sound other than speech in each stretch">{c.sounds.windows.map((w, i) => {
          const top = Object.entries(w.cats).filter(([k]) => k !== 'speech').sort((a, b) => b[1] - a[1])[0]; const role = top ? c.sounds!.hints[top[0]]?.[0] : undefined
          return <div key={i} title={top ? `${fmt(w.t0)}–${fmt(w.t1)}: ${top[0]} ${top[1].toFixed(2)}` : `${fmt(w.t0)}: nothing but speech`} style={{ width: `${100 * (Math.min(w.t1, w.t0 + 3) - w.t0) / (c.sounds!.windows[c.sounds!.windows.length - 1].t1)}%` }}
            className={role === 'avoid' ? 'bg-red-400' : role === 'voice' || role === 'energy' ? 'bg-emerald-500' : top ? 'bg-sky-400' : 'bg-stone-300 dark:bg-stone-700'} /> })}</div>
        <p className="mt-1 text-xs text-stone-500">green: cheering, laughter, shouting · blue: textures (water, nature, footsteps, bells, crowd) · red: sounds the mix pulls down (wind, handling noise, traffic, nearby music, beeps)</p>
      </Card>}
      <Card title="Transcript">
        <div className="mb-2 flex items-center gap-2 text-xs text-stone-500">other languages shown as
          <select value={mode} onChange={e => setMode(e.target.value as Mode)} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700"><option value="translated">translated</option><option value="original">original</option><option value="both">both</option></select></div>
        {c.transcript.length === 0 && <p className="text-sm text-stone-500">No speech recognised.</p>}
        <WordMarker folder={folder} onSaved={reload}>
        {c.transcript.map((l, i) => (
          <div key={i} id={`seg-${Math.round(l.t0 * 100)}`} className={`py-1 text-sm ${l.flagged ? 'opacity-50' : ''} ${focus != null && Math.abs(l.t0 - focus) < 0.05 ? 'rounded bg-emerald-100 px-1 dark:bg-emerald-950' : ''}`}>
            <span className="mr-2 font-mono text-xs text-stone-500">{fmt(l.t0)}</span>
            {l.who && <span className={`mr-2 rounded-full px-2 text-xs ${l.who === 'wearer' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-stone-200 text-stone-600 dark:bg-stone-800 dark:text-stone-400'}`}>{l.who === 'wearer' ? 'you' : 'other'}</span>}
            <PlayIcons folder={folder} clip={clip} t0={l.play0 ?? l.t0} t1={l.play1 ?? l.t1} original={!!c.audio_files?.original} clean={!!c.audio_files?.clean} />
            <Phrase text={l.text} en={l.text_en} lang={l.lang} mode={mode} word={l.words?.length ? { folder, clip, si: l.si, words: l.words, onSaved: reload, used } : undefined} />
          </div>
        ))}
        </WordMarker>
      </Card>
      {redo && <RedoDialog folder={folder} clip={clip} onClose={() => setRedo(false)} />}
      <PhotoStrip folder={folder} photos={photos} tz={tz} kind="clip" id={clip} />
      <NoteBox folder={folder} clip={clip} title="Notes for this clip" placeholder="What happened here? Names, places, how it felt, anything to mention or avoid…" />
    </div>
  )
}
