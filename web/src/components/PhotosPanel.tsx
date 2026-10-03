import { useRef, useState } from 'react'
import { api, type Photo } from '../api'
import { PhotoCard } from './PhotoStrip'

// The photos you took during the race: add them here (any common format; HEIC is converted). Each is placed in the race by the time stamp in the photo and on the map by its own GPS position, else by where the run was at that time;
// when the two disagree it says so. They are listed under the clip or gap they fall in, and have an icon on the overview map.
export default function PhotosPanel({ folder, photos, tz, onChanged, onOpen }: { folder: string; photos?: Photo[]; tz: string; onChanged: () => void; onOpen: (w: NonNullable<Photo['where']>) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState<string>(), [errs, setErrs] = useState<string[]>([])
  const add = async (files: FileList | File[] | null) => {
    const list = Array.from(files ?? []); if (!list.length) return
    setErrs([]); const bad: string[] = []
    for (const [i, f] of list.entries()) {
      setBusy(`Adding ${i + 1} of ${list.length}: ${f.name}`)
      try { await api.uploadPhoto(folder, f) } catch (e) { bad.push((e as Error).message) }
    }
    setBusy(undefined); setErrs(bad); onChanged()
  }
  const remove = async (p: Photo) => { try { await api.deletePhoto(folder, p.id) } catch (e) { setErrs([(e as Error).message]) } onChanged() }
  const flagged = (photos ?? []).filter(p => p.flag).length
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files) }}>
      <input ref={input} type="file" multiple hidden aria-label="Add photos" accept="image/*,.heic,.heif,.avif" onChange={e => { add(e.target.files); e.target.value = '' }} />
      <div className="mb-2 flex items-center justify-between text-sm">
        <b>Photos <span className="font-normal text-stone-500">({photos?.length ?? 0}{flagged ? `, ${flagged} to check` : ''})</span></b>
        <button disabled={!!busy} className="text-emerald-700 underline disabled:opacity-50 dark:text-emerald-400" onClick={() => input.current?.click()}>{busy ?? 'Add photos'}</button>
      </div>
      {errs.length > 0 && <ul role="alert" className="mb-2 space-y-0.5 text-sm text-red-600">{errs.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {photos && photos.length === 0 && !busy && <p className="text-sm text-stone-500">No photos yet. Add the ones you took during the race (or drop them here): the time in each says where in the race it was taken.</p>}
      <div className="flex flex-wrap gap-4">{(photos ?? []).map(p => <PhotoCard key={p.id} folder={folder} p={p} tz={tz} onOpen={onOpen} onRemove={() => remove(p)} />)}</div>
    </section>
  )
}
