import { useEffect, useState } from 'react'
import { api, type ClipInfo } from '../api'
import { usePoll } from '../usePoll'
import ProjectProgress from './ProjectProgress'
import TrackPanel from './TrackPanel'
import NoteBox from './NoteBox'
import ClipView from './ClipView'
import FilmDetails from './FilmDetails'

// The app is organised around clips: a list of clips (with thumbnails) on the left; with none selected the main area is the overview (progress, race track, notes for the whole
// folder); with one selected it is that clip's details and its own notes.
export default function Workspace({ folder, onChange }: { folder: string; onChange: () => void }) {
  const [sel, setSel] = useState<string | null>(null)
  const clips = usePoll(() => api.clips(folder).then(r => r.clips), 8000, [folder]) ?? []
  useEffect(() => { setSel(null) }, [folder])
  return (
    <div className="grid gap-4 md:grid-cols-[260px_1fr]">
      <aside className="md:sticky md:top-4 md:max-h-[calc(100vh-2rem)] md:overflow-auto">
        <button onClick={() => setSel(null)} className={`mb-2 w-full rounded-lg px-3 py-2 text-left text-sm font-medium ${sel === null ? 'bg-emerald-700 text-white' : 'bg-white hover:bg-stone-100 dark:bg-stone-900 dark:hover:bg-stone-800'}`}>Overview</button>
        <ul className="space-y-1">{clips.map(c => <Row key={c.id} folder={folder} c={c} active={sel === c.id} onClick={() => setSel(c.id)} />)}</ul>
      </aside>
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-3 text-sm"><span className="break-all font-mono text-stone-500">{folder}</span><button className="text-emerald-700 underline dark:text-emerald-400" onClick={onChange}>open another / new project</button></div>
        {sel === null ? (
          <div className="space-y-4">
            <FilmDetails folder={folder} />
            <ProjectProgress folder={folder} />
            <TrackPanel folder={folder} />
            <NoteBox folder={folder} title="Notes for the whole folder" placeholder="What was this? Who was there? What is the story of the day, in your own words…" />
          </div>
        ) : <ClipView folder={folder} clip={sel} />}
      </div>
    </div>
  )
}

function Row({ folder, c, active, onClick }: { folder: string; c: ClipInfo; active: boolean; onClick: () => void }) {
  const name = c.id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)
  return (
    <li onClick={onClick} className={`flex cursor-pointer gap-2 rounded-lg p-1.5 ${active ? 'bg-emerald-100 dark:bg-emerald-950' : 'hover:bg-stone-200/60 dark:hover:bg-stone-800'}`}>
      {c.thumb ? <img loading="lazy" src={api.thumbUrl(folder, c.id, c.thumb)} alt="" className="h-11 w-20 shrink-0 rounded object-cover" /> : <div className="h-11 w-20 shrink-0 rounded bg-stone-200 dark:bg-stone-800" />}
      <div className="min-w-0 flex-1 text-xs"><div className="truncate">{name}</div><div className="text-stone-500">{Math.round(c.duration_s)} s{c.candidates != null ? ` · ${c.candidates} moments` : ''}</div></div>
      {c.has_note && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-emerald-600" />}
    </li>
  )
}
