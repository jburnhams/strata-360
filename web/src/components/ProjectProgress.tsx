import { api, type Progress } from '../api'
import { usePoll } from '../usePoll'
import { useState } from 'react'
import RedoDialog from './RedoDialog'

const NEEDS: Record<string, string> = { wearer_profile: 'choose which face is you', camera_clock: 'confirm the camera clock' }
const LABEL: Record<string, string> = { new: 'New', processing: 'Processing…', needs_input: 'Waiting for you', complete: 'Complete' }

const Bar = ({ pct }: { pct: number }) => (
  <div className="h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"><div className="h-full bg-emerald-600 transition-all" style={{ width: `${pct}%` }} /></div>
)

export default function ProjectProgress({ folder }: { folder: string }) {
  const p = usePoll<Progress>(() => api.progress(folder), 2000, [folder])
  const [redo, setRedo] = useState<string | null | undefined>(undefined) // undefined = closed, null = all stages, string = that stage
  const log = usePoll(() => api.log(folder), 3000, [folder])
  if (!p) return null
  const mins = (s?: number | null) => (s ? ` · ${Math.round(s / 60)} min` : '')
  return (
    <div className="mt-4 rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div><b>{LABEL[p.state] ?? p.state}</b> <span className="text-sm text-stone-500">{p.clips ?? 0} clips · {p.footage_gb ?? 0} GB · {p.percent ?? 0}%{p.eta_s ? ` · about ${Math.round(p.eta_s / 60)} min left` : ''}</span></div>
      <div className="my-3"><Bar pct={p.percent ?? 0} /></div>
      {(p.stages ?? []).map(s => (
        <div key={s.name} className="my-1.5 grid grid-cols-[110px_1fr_110px] items-center gap-3 text-sm">
          <span title={s.note}>{s.name}</span><Bar pct={(100 * s.done) / Math.max(s.total, 1)} /><span className="text-stone-500">{s.done}/{s.total}{mins(s.eta_s)} <button className="ml-1 underline" onClick={() => setRedo(s.name)}>redo</button></span>
        </div>
      ))}
      {!!p.needs?.length && <p className="mt-3 text-sm text-stone-500">To do: {p.needs.map(n => NEEDS[n] ?? n).join(', ')}</p>}
      {!!p.active?.length && <p className="mt-2 text-xs text-stone-500">Working on: {p.active.map(a => `${a.stage} ${a.clip.replace(/^CAM_/, '').replace(/_D$/, '').slice(-4)}`).join(' · ')}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {p.state === 'complete' && <button className="rounded-lg bg-emerald-700 px-4 py-2 text-white">Go to results and export</button>}
        {p.state !== 'complete' && (
          <button disabled={(p.workers ?? 0) >= (p.max_workers ?? 3)} className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-50" onClick={() => api.run(folder)}>
            {p.workers ? `Add a worker (${p.workers} running)` : 'Start processing'}</button>
        )}
        {!!p.workers && <button className="rounded-lg border border-stone-300 px-4 py-2 dark:border-stone-700" onClick={() => api.stop(folder)}>Stop all</button>}
        <button className="ml-auto text-sm underline" onClick={() => setRedo(null)}>Reprocess…</button>
      </div>
      {redo !== undefined && <RedoDialog folder={folder} stage={redo ?? undefined} onClose={() => setRedo(undefined)} />}
      <pre className="mt-3 max-h-44 overflow-auto rounded-lg border border-stone-200 bg-stone-50 p-2 text-xs whitespace-pre-wrap dark:border-stone-800 dark:bg-stone-950">{(log?.lines ?? []).join('\n')}</pre>
    </div>
  )
}
