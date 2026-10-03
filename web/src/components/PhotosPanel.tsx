import { useRef, useState } from 'react'
import { api, type Photo, type PhotoJob } from '../api'
import PhotoCard from './PhotoCard'

// The photos you took during the race: add them here (any common format; HEIC is converted). Each is placed in the race by the time stamp in the photo and on the map by its own GPS position, else by where the run was at that time;
// when the two disagree it says so. They are listed under the clip or gap they fall in, and have an icon on the overview map.
export default function PhotosPanel({ folder, photos, tz, job, onChanged, onOpen }: { folder: string; photos?: Photo[]; tz: string; job?: PhotoJob; onChanged: () => void; onOpen: (p: Photo) => void }) {
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
  const analyse = async (force: boolean) => { setErrs([]); try { const r = await api.analysePhotos(folder, { force }); if (!r.started) setErrs([r.reason || 'could not start']) } catch (e) { setErrs([(e as Error).message]) } onChanged() }
  const flagged = (photos ?? []).filter(p => p.flag).length, analysed = (photos ?? []).filter(p => p.analysis?.stages.length).length
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files) }}>
      <input ref={input} type="file" multiple hidden aria-label="Add photos" accept="image/*,.heic,.heif,.avif" onChange={e => { add(e.target.files); e.target.value = '' }} />
      <div className="mb-2 flex items-center justify-between text-sm">
        <b>Photos <span className="font-normal text-stone-500">({photos?.length ?? 0}{flagged ? `, ${flagged} to check` : ''})</span></b>
        <span className="flex items-center gap-3">
          {(photos?.length ?? 0) > 0 && <button disabled={!!job?.running} className="text-emerald-700 underline disabled:opacity-50 dark:text-emerald-400" title="Run the clip stages that make sense for a photo (exposure, quality, places, people, who is in it, face, scene, overlay); only what is out of date" onClick={() => analyse(false)}>{job?.running ? 'Analysing…' : analysed < (photos?.length ?? 0) ? 'Analyse photos' : 'Analyse again'}</button>}
          {(photos?.length ?? 0) > 0 && analysed > 0 && !job?.running && <button className="text-stone-500 underline" title="Redo every stage for every photo" onClick={() => analyse(true)}>Redo all</button>}
          <button disabled={!!busy} className="text-emerald-700 underline disabled:opacity-50 dark:text-emerald-400" onClick={() => input.current?.click()}>{busy ?? 'Add photos'}</button>
        </span>
      </div>
      {job?.running && <p data-job="" className="mb-2 text-xs text-stone-500">{job.log.at(-1) ?? 'starting…'}</p>}
      {!job?.running && job?.error && <p role="alert" className="mb-2 text-sm text-red-600">The analysis stopped: {job.error}</p>}
      {errs.length > 0 && <ul role="alert" className="mb-2 space-y-0.5 text-sm text-red-600">{errs.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {photos && photos.length === 0 && !busy && <p className="text-sm text-stone-500">No photos yet. Add the ones you took during the race (or drop them here): the time in each says where in the race it was taken.</p>}
      <div className="flex flex-wrap gap-4">{(photos ?? []).map(p => <PhotoCard key={p.id} folder={folder} p={p} tz={tz} onOpen={() => onOpen(p)} onRemove={() => remove(p)} onMotion={onChanged} />)}</div>
    </section>
  )
}
