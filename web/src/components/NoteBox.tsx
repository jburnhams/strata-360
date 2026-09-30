import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// A note saved as you type: for the whole folder (clip undefined) or one clip. Used, with the transcript and the track data, to write the voice-over script.
export default function NoteBox({ folder, clip, title, placeholder }: { folder: string; clip?: string; title: string; placeholder: string }) {
  const [text, setText] = useState('')
  const [saved, setSaved] = useState(true)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    let live = true
    setSaved(true)
    api.notes(folder).then(n => live && setText(clip ? n.clips[clip] ?? '' : n.folder))
    return () => { live = false; window.clearTimeout(timer.current) }
  }, [folder, clip])
  const change = (v: string) => {
    setText(v); setSaved(false)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => { await api.saveNote(folder, v, clip); setSaved(true) }, 600)
  }
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-1 flex items-center justify-between text-sm"><b>{title}</b><span className="text-stone-500">{saved ? 'saved' : 'saving…'}</span></div>
      <textarea value={text} onChange={e => change(e.target.value)} rows={clip ? 6 : 10} placeholder={placeholder}
        className="w-full rounded-lg border border-stone-300 bg-stone-50 p-3 text-sm dark:border-stone-700 dark:bg-stone-950" />
      <p className="mt-1 text-xs text-stone-500">Used with the transcript, the track data and what the camera sees to write the voice-over script.</p>
    </section>
  )
}
