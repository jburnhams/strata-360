import { useEffect, useState } from 'react'
import { api, type Browse } from '../api'
import { PanelSkeleton } from './Skeleton'

// Pick a project: browse the server's allowed folders. A folder that already is a project opens straight away (its sub-folders are never offered);
// a folder with camera files can become a new project; anything else is just a place to look further.
export default function FolderBrowser({ onChoose, onCancel }: { onChoose: (folder: string) => void; onCancel?: () => void }) {
  const [b, setB] = useState<Browse>()
  const [err, setErr] = useState<string>()
  const go = (path?: string) => api.browse(path).then(x => {
    setErr(undefined)
    if (x.is_project) onChoose(x.path)
    else setB(x)
  }).catch(e => setErr(e.message))
  useEffect(() => { go() }, [])
  if (err) return <p className="text-muted-foreground">{err}</p>
  if (!b) return <PanelSkeleton title="Folders" rows={6} />
  return (
    <div className="rounded-overlay border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between"><span className="break-all font-mono type-caption text-muted-foreground">{b.path}</span>{onCancel && <button className="type-body-sm text-primary underline" onClick={onCancel}>cancel</button>}</div>
      <ul className="divide-y divide-border">
        {b.parent && <Row name=".." onClick={() => go(b.parent!)} />}
        {b.entries.map(e => <Row key={e.path} name={e.name} project={e.is_project} onClick={() => go(e.path)} />)}
      </ul>
      <div className="mt-3 flex items-center gap-3">
        <button disabled={!b.can_create} className="rounded-surface bg-primary px-4 py-2 text-primary-foreground hover:bg-primary disabled:opacity-40" onClick={() => onChoose(b.path)}>Create project here</button>
        <span className="type-body-sm text-muted-foreground">
          {b.can_create ? (b.footage_here ? `${b.footage_here} camera file(s) here` : 'camera files found in the sub-folders') : 'open a folder that holds camera files (or an existing project)'}
        </span>
      </div>
    </div>
  )
}

function Row({ name, project, onClick }: { name: string; project?: boolean; onClick: () => void }) {
  return (
    <li className="flex cursor-pointer items-center gap-3 px-1 py-2 hover:bg-primary-3" onClick={onClick}>
      <span className="flex-1">{name}</span>
      {project && <span className="rounded-pill border border-primary px-2 type-caption text-primary">project</span>}
    </li>
  )
}
