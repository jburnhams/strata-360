import { useRef, useState } from 'react'
import { api, type Photo, type PhotoJob } from '../api'
import PhotoCard from './PhotoCard'
import { Alert, Button, Tooltip } from 'strata-react'

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
    <section className="rounded-overlay border border-border bg-card p-4" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files) }}>
      <input ref={input} type="file" multiple hidden aria-label="Add photos" accept="image/*,.heic,.heif,.avif" onChange={e => { add(e.target.files); e.target.value = '' }} />
      <div className="mb-2 flex items-center justify-between type-body-sm">
        <b>Photos <span className="font-normal text-muted-foreground">({photos?.length ?? 0}{flagged ? `, ${flagged} to check` : ''})</span></b>
        <span className="flex items-center gap-3">
          {(photos?.length ?? 0) > 0 && <Tooltip label="Run the clip stages that make sense for a photo (exposure, quality, places, people, who is in it, face, scene, overlay); only what is out of date"><Button variant="link" disabled={!!job?.running} onClick={() => analyse(false)}>{job?.running ? 'Analysing…' : analysed < (photos?.length ?? 0) ? 'Analyse photos' : 'Analyse again'}</Button></Tooltip>}
          {(photos?.length ?? 0) > 0 && analysed > 0 && !job?.running && <Tooltip label="Redo every stage for every photo"><Button variant="link" onClick={() => analyse(true)}>Redo all</Button></Tooltip>}
          <Button variant="link" disabled={!!busy} onClick={() => input.current?.click()}>{busy ?? 'Add photos'}</Button>
        </span>
      </div>
      {job?.running && <p data-job="" className="mb-2 type-caption text-muted-foreground">{job.log.at(-1) ?? 'starting…'}</p>}
      {!job?.running && job?.error && <Alert tone="danger" announce className="mb-2">The analysis stopped: {job.error}</Alert>}
      {errs.length > 0 && <ul role="alert" className="mb-2 space-y-0.5 type-body-sm text-danger">{errs.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {photos && photos.length === 0 && !busy && <p className="type-body-sm text-muted-foreground">No photos yet. Add the ones you took during the race (or drop them here): the time in each says where in the race it was taken.</p>}
      <div className="flex flex-wrap gap-4">{(photos ?? []).map(p => <PhotoCard key={p.id} folder={folder} p={p} tz={tz} onOpen={() => onOpen(p)} onRemove={() => remove(p)} onMotion={onChanged} />)}</div>
    </section>
  )
}
