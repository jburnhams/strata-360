import { useEffect, useState } from 'react'
import { api, type ClipInfo, type Gap } from '../api'
import { usePoll } from '../usePoll'
import ProjectProgress from './ProjectProgress'
import TrackPanel from './TrackPanel'
import ClockPanel from './ClockPanel'
import WhoPanel from './WhoPanel'
import NoteBox from './NoteBox'
import ClipView from './ClipView'
import { Skeleton } from './Skeleton'
import TranscriptPanel from './TranscriptPanel'
import ScriptPanel from './ScriptPanel'
import ScriptDraftPanel from './ScriptDraftPanel'
import VoiceoverPanel from './VoiceoverPanel'
import Timeline from './Timeline'
import FilmDetails from './FilmDetails'
import MusicPanel from './MusicPanel'
import GapView from './GapView'
import PhotosPanel from './PhotosPanel'
import StreetViewPage from './StreetViewPage'
import { thumbVersion, useThumbOverlay } from '../thumbOverlay'

// The app is organised around clips: a list of clips (with thumbnails) on the left; with none selected the main area is the overview (progress, race track, notes for the whole
// folder); with one selected it is that clip's details and its own notes.
export default function Workspace({ folder, onChange }: { folder: string; onChange: () => void }) {
  const [sel, setSel] = useState<string | null>(null)       // null = overview, '@timeline' = the film's timeline, else a clip id
  const [focus, setFocus] = useState<number | undefined>(undefined)
  const meta = usePoll(() => api.meta(folder), 60000, [folder])
  const clips = usePoll(() => api.clips(folder).then(r => r.clips), 8000, [folder])
  const [photoTick, setPhotoTick] = useState(0)
  const photoData = usePoll(() => api.photos(folder), 8000, [folder, photoTick]); const photos = photoData?.photos; const tz = meta?.timezone ?? photoData?.tz ?? 'Europe/Brussels'
  const openWhere = (w: { kind: 'clip' | 'gap'; id: string }) => { setFocus(undefined); setSel(w.kind === 'gap' ? `@gap:${w.id}` : w.id) }
  const gaps = usePoll(() => api.gaps(folder).then(r => r.gaps), 8000, [folder])
  const [overlay, setOverlay] = useThumbOverlay()
  useEffect(() => { setSel(null); setFocus(undefined) }, [folder])
  return (
    <div className="grid gap-4 md:grid-cols-[260px_1fr]">
      <aside className="flex flex-col md:sticky md:top-4 md:h-[calc(100vh-2rem)]">
        <button onClick={() => setSel(null)} className={`mb-2 w-full shrink-0 rounded-lg px-3 py-2 text-left text-sm font-medium ${sel === null ? 'bg-emerald-700 text-white' : 'bg-white hover:bg-stone-100 dark:bg-stone-900 dark:hover:bg-stone-800'}`}>Overview</button>
        <button onClick={() => setSel('@streetview')} className={`mb-2 w-full shrink-0 rounded-lg px-3 py-2 text-left text-sm font-medium ${sel === '@streetview' ? 'bg-emerald-700 text-white' : 'bg-white hover:bg-stone-100 dark:bg-stone-900 dark:hover:bg-stone-800'}`}>Street view</button>
        <button onClick={() => setSel('@timeline')} className={`mb-2 w-full shrink-0 rounded-lg px-3 py-2 text-left text-sm font-medium ${sel === '@timeline' ? 'bg-emerald-700 text-white' : 'bg-white hover:bg-stone-100 dark:bg-stone-900 dark:hover:bg-stone-800'}`}>Timeline</button>
        <label className="mb-1 flex shrink-0 items-center gap-2 px-1 text-xs text-stone-600 dark:text-stone-400" title="Show the thumbnails with the race overlay (clock, numbers, maps) as the film will have it, where the thumb_overlay stage has made one">
          <input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} /> Overlay on thumbnails
        </label>
        <ul className="min-h-0 flex-1 space-y-1 overflow-auto md:pr-1">
          {clips === undefined ? Array.from({ length: 8 }, (_, i) => <li key={i} className="flex gap-2 p-1.5"><Skeleton className="h-11 w-20 shrink-0" /><div className="flex-1 space-y-1.5"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-1/2" /></div></li>)
            : clips.map(c => <Row key={c.id} folder={folder} c={c} overlay={overlay} active={sel === c.id} onClick={() => { setFocus(undefined); setSel(c.id) }} />)}
          {gaps !== undefined && gaps.length > 0 && <li className="px-1 pt-2 text-xs font-medium uppercase tracking-wide text-stone-500">Gaps in the footage</li>}
          {(gaps ?? []).map(g => <GapRow key={g.id} g={g} active={sel === `@gap:${g.id}`} onClick={() => { setFocus(undefined); setSel(`@gap:${g.id}`) }} />)}
        </ul>
      </aside>
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-3 text-sm"><span className="break-all font-mono text-stone-500">{folder}</span><button className="text-emerald-700 underline dark:text-emerald-400" onClick={onChange}>open another / new project</button></div>
        {sel === null ? (
          <div className="space-y-4">
            <FilmDetails folder={folder} />
            <ProjectProgress folder={folder} onResults={() => setSel('@timeline')} />
            <TrackPanel folder={folder} tz={tz} photos={photos} onOpenPhoto={p => p.where && openWhere(p.where)} onOpenClip={c => { setFocus(undefined); setSel(c) }} onOpenGap={g => { setFocus(undefined); setSel(`@gap:${g}`) }} />
            <PhotosPanel folder={folder} photos={photos} tz={tz} job={photoData?.job} onChanged={() => setPhotoTick(t => t + 1)} onOpen={openWhere} />
            <MusicPanel folder={folder} />
            <ClockPanel folder={folder} />
            <WhoPanel folder={folder} />
            <NoteBox folder={folder} title="Notes for the whole folder" placeholder="What was this? Who was there? What is the story of the day, in your own words…" />
            <ScriptDraftPanel folder={folder} />
            <ScriptPanel folder={folder} onOpen={c => { setFocus(undefined); setSel(c) }} />
            <VoiceoverPanel folder={folder} />
            <TranscriptPanel folder={folder} clips={clips ?? []} tz={meta?.timezone ?? 'Europe/Brussels'} onOpen={(c, t) => { setFocus(t); setSel(c) }} />
          </div>
        ) : sel === '@streetview' ? <StreetViewPage folder={folder} />
          : sel === '@timeline' ? <Timeline folder={folder} clips={clips ?? []} onOpenClip={c => { setFocus(undefined); setSel(c) }} />
          : sel.startsWith('@gap:') ? <GapView folder={folder} gap={sel.slice(5)} photos={photos} tz={tz} onPhotosChanged={() => setPhotoTick(t => t + 1)} />
          : <ClipView folder={folder} clip={sel} focus={focus} photos={photos} tz={tz} onPhotosChanged={() => setPhotoTick(t => t + 1)} />}
      </div>
    </div>
  )
}

function GapRow({ g, active, onClick }: { g: Gap; active: boolean; onClick: () => void }) {
  const c = g.clips.find(x => x.id === g.id), s = g.settings
  const state = c?.rendering ? 'rendering…' : c?.exists ? (c.kind === 'flyover' ? '3D' : '2D') + ` · ${c.seconds} s` : c ? 'planned' : 'no clip'
  return (
    <li onClick={onClick} data-in-film={g.in_film ? '' : undefined} data-selected={active ? '' : undefined} className={`flex cursor-pointer gap-2 rounded-lg border-2 p-1.5 ${g.in_film ? 'border-emerald-600' : 'border-transparent'} ${active ? 'bg-yellow-100 ring-2 ring-yellow-400 dark:bg-yellow-950 dark:ring-yellow-500' : 'hover:bg-stone-200/60 dark:hover:bg-stone-800'}`}>
      <div className={`flex h-11 w-20 shrink-0 items-center justify-center rounded text-sm font-semibold ${c?.exists ? 'bg-emerald-200 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100' : 'bg-stone-200 text-stone-600 dark:bg-stone-800 dark:text-stone-400'}`}>{g.id}</div>
      <div className="min-w-0 flex-1 text-xs"><div className="truncate">{g.local_start}</div><div className="text-stone-500">{(g.duration_s / 3600).toFixed(1)} h · {state}{s?.must ? ' · must use' : ''}</div></div>
    </li>
  )
}

function Row({ folder, c, overlay, active, onClick }: { folder: string; c: ClipInfo; overlay: boolean; active: boolean; onClick: () => void }) {
  const name = c.id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)
  return (
    <li onClick={onClick} data-in-film={c.in_film ? '' : undefined} data-selected={active ? '' : undefined} className={`flex cursor-pointer gap-2 rounded-lg border-2 p-1.5 ${c.in_film ? 'border-emerald-600' : 'border-transparent'} ${active ? 'bg-yellow-100 ring-2 ring-yellow-400 dark:bg-yellow-950 dark:ring-yellow-500' : 'hover:bg-stone-200/60 dark:hover:bg-stone-800'}`}>
      {c.thumb ? <img loading="lazy" src={api.thumbUrl(folder, c.id, thumbVersion(c, overlay), overlay)} alt="" className="h-11 w-20 shrink-0 rounded object-cover" /> : <div className="h-11 w-20 shrink-0 rounded bg-stone-200 dark:bg-stone-800" />}
      <div className="min-w-0 flex-1 text-xs"><div className="truncate">{name}</div><div className="text-stone-500">{Math.round(c.duration_s)} s{c.candidates != null ? ` · ${c.candidates} moments` : ''}</div></div>
      {c.has_note && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-emerald-600" />}
    </li>
  )
}
