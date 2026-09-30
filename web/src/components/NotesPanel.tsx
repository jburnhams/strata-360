import { useEffect, useRef, useState } from 'react'
import { api, type ClipInfo, type Notes } from '../api'

// Notes for the whole folder (the race: what it was, who was there, the story) and per clip (what happened, names, places, feelings).
// They are saved as you type and later go, with the transcript and the track data, to the voice-over script writer.
export default function NotesPanel({ folder }: { folder: string }) {
  const [notes, setNotes] = useState<Notes>()
  const [clips, setClips] = useState<ClipInfo[]>([])
  const [sel, setSel] = useState<string | null>(null) // null = the folder note
  const [text, setText] = useState('')
  const [saved, setSaved] = useState(true)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => { api.notes(folder).then(setNotes); api.clips(folder).then(r => setClips(r.clips)) }, [folder])
  useEffect(() => { if (notes) setText(sel === null ? notes.folder : notes.clips[sel] ?? ''); setSaved(true) }, [sel, notes?.folder === undefined])

  const change = (v: string) => {
    setText(v); setSaved(false)
    window.clearTimeout(timer.current)
    const target = sel
    timer.current = window.setTimeout(async () => {
      const n = await api.saveNote(folder, v, target ?? undefined)
      setNotes(n); setSaved(true)
      setClips(cs => cs.map(c => (c.id === target ? { ...c, has_note: !!v.trim() } : c)))
    }, 600)
  }

  return (
    <div className="mt-4 grid gap-4 rounded-xl border border-stone-200 bg-white p-4 md:grid-cols-[220px_1fr] dark:border-stone-800 dark:bg-stone-900">
      <ul className="max-h-96 overflow-auto text-sm">
        <Item active={sel === null} onClick={() => setSel(null)} label="Whole folder" dot={!!notes?.folder.trim()} />
        {clips.map(c => (
          <Item key={c.id} active={sel === c.id} onClick={() => setSel(c.id)} label={c.id.replace(/^CAM_/, '').replace(/_D$/, '')} sub={`${c.duration_s}s`} dot={c.has_note} />
        ))}
      </ul>
      <div>
        <div className="mb-1 flex items-center justify-between text-sm text-stone-500">
          <span>{sel === null ? 'Notes for the whole folder' : `Notes for ${sel}`}</span><span>{saved ? 'saved' : 'saving…'}</span>
        </div>
        <textarea
          value={text} onChange={e => change(e.target.value)} rows={12}
          placeholder={sel === null ? 'What was this? Who was there? What is the story of the day, in your own words…' : 'What happened here? Names, places, how it felt, anything to mention or avoid…'}
          className="w-full rounded-lg border border-stone-300 bg-stone-50 p-3 text-sm dark:border-stone-700 dark:bg-stone-950"
        />
        <p className="mt-1 text-xs text-stone-500">Used with the transcript, the track data (pace, climb, time of day, how far into the race) and what the camera sees to write the voice-over script.</p>
      </div>
    </div>
  )
}

function Item({ label, sub, active, dot, onClick }: { label: string; sub?: string; active: boolean; dot: boolean; onClick: () => void }) {
  return (
    <li onClick={onClick} className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1 ${active ? 'bg-emerald-100 dark:bg-emerald-950' : 'hover:bg-stone-100 dark:hover:bg-stone-800'}`}>
      <span className="flex-1 truncate">{label}</span><span className="text-xs text-stone-500">{sub}</span>{dot && <span className="h-2 w-2 rounded-full bg-emerald-600" />}
    </li>
  )
}
