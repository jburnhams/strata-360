import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { PanelSkeleton } from './Skeleton'
import { Checkbox, Textarea } from 'strata-react'

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
    <section className="rounded-overlay border border-border bg-card p-4">
      <div className="mb-1 flex items-center justify-between type-body-sm"><b>{title}</b><span className="text-muted-foreground">{saved ? 'saved' : 'saving…'}</span></div>
      <Textarea value={text} onChange={e => change(e.target.value)} rows={clip ? 6 : 10} placeholder={placeholder}
        className="w-full" />
      <p className="mt-1 type-caption text-muted-foreground">Used with the transcript, the track data and what the camera sees to write the voice-over script.</p>
      <label className="mt-3 block type-body-sm"><b>Voice-over MUST INCLUDE</b> <span className="type-caption text-muted-foreground">{clip ? 'one piece of narration per line; each is spoken word for word inside this clip' : 'one piece of narration per line; each is spoken word for word somewhere in the film'}</span>
        <Textarea value={vo} onChange={e => { setVo(e.target.value); saveVo(e.target.value, ordered) }} rows={3} placeholder="Narration you want in the film, written as it should be spoken"
          className="mt-1 w-full" /></label>
      {!clip && <Checkbox label="keep them in the order written (otherwise they can come in any order)" checked={ordered} onCheckedChange={(checked: boolean) => { setOrdered(checked); saveVo(vo, checked, true) }} />}
    </section>
  )
}
