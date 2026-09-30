import { useEffect, useState } from 'react'
import { api, type Browse } from '../api'

export default function FolderBrowser({ onChoose }: { onChoose: (folder: string) => void }) {
  const [b, setB] = useState<Browse>()
  const [err, setErr] = useState<string>()
  const go = (path?: string) => api.browse(path).then(x => { setB(x); setErr(undefined) }).catch(e => setErr(e.message))
  useEffect(() => { go() }, [])
  if (err) return <p className="text-stone-500">{err}</p>
  if (!b) return <p className="text-stone-500">Loading…</p>
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-2 break-all font-mono text-xs text-stone-500">{b.path}</div>
      <ul className="divide-y divide-stone-200 dark:divide-stone-800">
        {b.parent && <Row name=".." onClick={() => go(b.parent!)} />}
        {b.entries.map(e => <Row key={e.path} name={e.name} project={e.is_project} onClick={() => go(e.path)} />)}
      </ul>
      <div className="mt-3 flex items-center gap-3">
        <button className="rounded-lg bg-emerald-700 px-4 py-2 text-white hover:bg-emerald-600" onClick={() => onChoose(b.path)}>Use this folder</button>
        <span className="text-sm text-stone-500">
          {b.footage_here ? `${b.footage_here} camera file(s) here` : 'no camera files directly in this folder (subfolders are searched too)'}
          {b.is_project ? ' · already a project' : ''}
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
