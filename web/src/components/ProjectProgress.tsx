import { api, type Progress } from '../api'
import { usePoll } from '../usePoll'
import { useState } from 'react'
import RedoDialog from './RedoDialog'
import { PanelSkeleton } from './Skeleton'

const NEEDS: Record<string, string> = { wearer_profile: 'choose which face is you', camera_clock: 'confirm the camera clock' }
const LABEL: Record<string, string> = { new: 'New', processing: 'Processing…', needs_input: 'Waiting for you', complete: 'Complete' }

const Bar = ({ pct }: { pct: number }) => (
  <div className="h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"><div className="h-full bg-emerald-600 transition-all" style={{ width: `${pct}%` }} /></div>
)

export default function ProjectProgress({ folder }: { folder: string }) {
  const p = usePoll<Progress>(() => api.progress(folder), 2000, [folder])
  const [redo, setRedo] = useState<string | null | undefined>(undefined) // undefined = closed, null = all stages, string = that stage
  const log = usePoll(() => api.log(folder), 3000, [folder])
  if (!p) return <PanelSkeleton title="Progress" rows={6} />
  const mins = (s?: number | null) => (s ? ` · ${Math.round(s / 60)} min` : '')
  return (
    <div className="mt-4 rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div><b>{LABEL[p.state] ?? p.state}</b> <span className="text-sm text-stone-500">{p.clips ?? 0} clips · {p.footage_gb ?? 0} GB · {p.percent ?? 0}%{p.eta_s ? ` · about ${Math.round(p.eta_s / 60)} min left` : ''}</span></div>
      <div className="my-3"><Bar pct={p.percent ?? 0} /></div>
      {(p.stages ?? []).map(s => (
        <div key={s.name} className="my-1.5 text-sm">
          <div className="grid grid-cols-[110px_1fr_130px] items-center gap-3">
            <span title={s.note}>{s.name}</span><Bar pct={(100 * s.done) / Math.max(s.total, 1)} />
            <span className="text-stone-500">{s.done}/{s.total}{mins(s.eta_s)} <button className="ml-1 underline" onClick={() => setRedo(s.name)}>redo</button></span>
          </div>
          {!!s.running?.length && (
            <div className="mt-1 flex flex-wrap gap-1.5 pl-[122px]">
              {s.running.map(r => (
                <span key={r.pid} className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />clip {r.clip.replace(/_D$/, '').slice(-4)}
                  <button title={`stop this worker (pid ${r.pid})`} className="ml-1 font-bold" onClick={() => api.stop(folder, r.pid)}>×</button>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
      {!!p.needs?.length && <p className="mt-3 text-sm text-stone-500">To do: {p.needs.map(n => NEEDS[n] ?? n).join(', ')}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        {p.state === 'complete' && <button className="rounded-lg bg-emerald-700 px-4 py-2 text-white">Go to results and export</button>}
        {p.state !== 'complete' && !p.workers && (p.runnable ?? 0) > 0 && <button className="rounded-lg bg-emerald-700 px-4 py-2 text-white" onClick={() => api.run(folder)}>Start processing</button>}
        {!!p.workers && (
          <span className="text-stone-500">
            {p.workers} of {p.max_workers ?? 3} workers running
            {(p.runnable ?? 0) === 0 ? ' · nothing else can start yet (waiting for the running stages)' : (p.workers ?? 0) >= (p.max_workers ?? 3) ? ' (the maximum: each model needs a few GB of memory)' : ''}
          </span>
        )}
        {!!p.workers && (p.workers ?? 0) < (p.max_workers ?? 3) && (p.runnable ?? 0) > 0 && (
          <button className="rounded-lg border border-emerald-700 px-3 py-1.5 text-emerald-800 dark:text-emerald-300" onClick={() => api.run(folder)}>Add a worker ({p.runnable} items waiting)</button>
        )}
        {!!p.workers && <button className="rounded-lg border border-stone-300 px-3 py-1.5 dark:border-stone-700" onClick={() => api.stop(folder)}>Stop all</button>}
        <button className="ml-auto underline" onClick={() => setRedo(null)}>Reprocess…</button>
      </div>
      {redo !== undefined && <RedoDialog folder={folder} stage={redo ?? undefined} onClose={() => setRedo(undefined)} />}
      <pre className="mt-3 max-h-44 overflow-auto rounded-lg border border-stone-200 bg-stone-50 p-2 text-xs whitespace-pre-wrap dark:border-stone-800 dark:bg-stone-950">{(log?.lines ?? []).join('\n')}</pre>
    </div>
  )
}
