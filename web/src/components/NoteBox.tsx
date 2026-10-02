import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { PanelSkeleton } from './Skeleton'

// A note saved as you type: for the whole folder (clip undefined) or one clip. Used, with the transcript and the track data, to write the voice-over script.
export default function NoteBox({ folder, clip, title, placeholder }: { folder: string; clip?: string; title: string; placeholder: string }) {
  const [text, setText] = useState<string>()
  const [vo, setVo] = useState(''), [ordered, setOrdered] = useState(true)
  const [pending, setPending] = useState({ note: false, vo: false })
  const timer = useRef<number | undefined>(undefined), voTimer = useRef<number | undefined>(undefined)
  const saved = !pending.note && !pending.vo
  useEffect(() => {
    let live = true
    setPending({ note: false, vo: false }); setText(undefined)
    api.notes(folder)
      .then(n => { if (!live) return; setText(clip ? n.clips[clip] ?? '' : n.folder); setVo(clip ? n.vo_must?.clips[clip] ?? '' : n.vo_must?.folder ?? ''); setOrdered(n.vo_must?.folder_ordered ?? true) })
      .catch(() => live && setText(''))
    return () => { live = false; window.clearTimeout(timer.current); window.clearTimeout(voTimer.current) }
  }, [folder, clip])
  if (text === undefined) return <PanelSkeleton title={title} rows={clip ? 3 : 5} />
  const change = (v: string) => {
    setText(v); setPending(p => ({ ...p, note: true }))
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => { await api.saveNote(folder, v, clip).catch(() => {}); setPending(p => ({ ...p, note: false })) }, 600)
  }
  const saveVo = (v: string, o: boolean, now = false) => {
    setPending(p => ({ ...p, vo: true })); window.clearTimeout(voTimer.current)
    const run = async () => { await api.saveVo(folder, v, clip, clip ? undefined : o).catch(() => {}); setPending(p => ({ ...p, vo: false })) }
    if (now) void run(); else voTimer.current = window.setTimeout(run, 600)
  }
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-1 flex items-center justify-between text-sm"><b>{title}</b><span className="text-stone-500">{saved ? 'saved' : 'saving…'}</span></div>
      <textarea value={text} onChange={e => change(e.target.value)} rows={clip ? 6 : 10} placeholder={placeholder}
        className="w-full rounded-lg border border-stone-300 bg-stone-50 p-3 text-sm dark:border-stone-700 dark:bg-stone-950" />
      <p className="mt-1 text-xs text-stone-500">Used with the transcript, the track data and what the camera sees to write the voice-over script.</p>
      <label className="mt-3 block text-sm"><b>Voice-over MUST INCLUDE</b> <span className="text-xs text-stone-500">{clip ? 'one piece of narration per line; each is spoken word for word inside this clip' : 'one piece of narration per line; each is spoken word for word somewhere in the film'}</span>
        <textarea value={vo} onChange={e => { setVo(e.target.value); saveVo(e.target.value, ordered) }} rows={3} placeholder="Narration you want in the film, written as it should be spoken"
          className="mt-1 w-full rounded-lg border border-stone-300 bg-stone-50 p-3 text-sm dark:border-stone-700 dark:bg-stone-950" /></label>
      {!clip && <label className="flex items-center gap-1.5 text-xs text-stone-500"><input type="checkbox" checked={ordered} onChange={e => { setOrdered(e.target.checked); saveVo(vo, e.target.checked, true) }} /> keep them in the order written (otherwise they can come in any order)</label>}
    </section>
  )
}
