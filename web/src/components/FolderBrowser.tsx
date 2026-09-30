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
  if (err) return <p className="text-stone-500">{err}</p>
  if (!b) return <PanelSkeleton title="Folders" rows={6} />
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-2 flex items-center justify-between"><span className="break-all font-mono text-xs text-stone-500">{b.path}</span>{onCancel && <button className="text-sm text-emerald-700 underline dark:text-emerald-400" onClick={onCancel}>cancel</button>}</div>
      <ul className="divide-y divide-stone-200 dark:divide-stone-800">
        {b.parent && <Row name=".." onClick={() => go(b.parent!)} />}
        {b.entries.map(e => <Row key={e.path} name={e.name} project={e.is_project} onClick={() => go(e.path)} />)}
      </ul>
      <div className="mt-3 flex items-center gap-3">
        <button disabled={!b.can_create} className="rounded-lg bg-emerald-700 px-4 py-2 text-white hover:bg-emerald-600 disabled:opacity-40" onClick={() => onChoose(b.path)}>Create project here</button>
        <span className="text-sm text-stone-500">
          {b.can_create ? (b.footage_here ? `${b.footage_here} camera file(s) here` : 'camera files found in the sub-folders') : 'open a folder that holds camera files (or an existing project)'}
        </span>
      </div>
    </div>
  )
}

function Row({ name, project, onClick }: { name: string; project?: boolean; onClick: () => void }) {
  return (
    <li className="flex cursor-pointer items-center gap-3 px-1 py-2 hover:bg-emerald-50 dark:hover:bg-emerald-950/40" onClick={onClick}>
      <span className="flex-1">{name}</span>
      {project && <span className="rounded-full border border-emerald-600 px-2 text-xs text-emerald-700 dark:text-emerald-400">project</span>}
    </li>
  )
}
