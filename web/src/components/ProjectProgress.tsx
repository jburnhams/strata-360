import { api, type Progress } from '../api'
import { usePoll } from '../usePoll'
import { useState } from 'react'
import RedoDialog from './RedoDialog'
import { PanelSkeleton } from './Skeleton'
import Health from './Health'
import { Button, Tooltip } from 'strata-react'

const NEEDS: Record<string, string> = { wearer_profile: 'choose which face is you', camera_clock: 'confirm the camera clock', race_track: 'add the race track (a Garmin .fit or a .gpx): the places stage is paused until then' }
const LABEL: Record<string, string> = { new: 'New', processing: 'Processing…', needs_input: 'Waiting for you', complete: 'Complete' }

const Bar = ({ pct }: { pct: number }) => (
  <div className="h-2 overflow-hidden rounded-pill bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>
)

export default function ProjectProgress({ folder, onResults }: { folder: string; onResults?: () => void }) {
  const p = usePoll<Progress>(() => api.progress(folder), 2000, [folder])
  const [redo, setRedo] = useState<string | null | undefined>(undefined) // undefined = closed, null = all stages, string = that stage
  const cov = usePoll(() => api.coverage(folder).catch(() => null), 10000, [folder])
  const log = usePoll(() => api.log(folder), 3000, [folder])
  if (!p) return <PanelSkeleton title="Progress" rows={6} />
  const mins = (s?: number | null) => (s ? ` · ${Math.round(s / 60)} min` : '')
  return (
    <div className="mt-4 rounded-overlay border border-border bg-card p-4">
      <div><b>{LABEL[p.state] ?? p.state}</b> <span className="type-body-sm text-muted-foreground">{p.clips ?? 0} clips · {p.footage_gb ?? 0} GB · {p.percent ?? 0}%{p.eta_s ? ` · about ${Math.round(p.eta_s / 60)} min left` : ''}</span></div>
      <div className="my-3"><Bar pct={p.percent ?? 0} /></div>
      {(p.stages ?? []).map(s => (
        <div key={s.name} className="my-1.5 type-body-sm">
          <div className="grid grid-cols-[110px_1fr_130px] items-center gap-3">
            <span title={s.note}>{s.name}{s.waiting && <span className="ml-1 type-caption text-warning" title={`paused: waiting for ${s.waiting}`}>⏸</span>}</span><Bar pct={(100 * s.done) / Math.max(s.total, 1)} />
            <span className="text-muted-foreground">{s.done}/{s.total}{mins(s.eta_s)} <Button variant="link" className="ml-1" onClick={() => setRedo(s.name)}>redo</Button></span>
          </div>
          <Health h={s.retry} className="ml-[122px]" />
          {!!s.running?.length && (
            <div className="mt-1 flex flex-wrap gap-1.5 pl-[122px]">
              {s.running.map(r => (
                <span key={r.pid} className="inline-flex items-center gap-1 rounded-pill bg-warning-subtle px-2 py-0.5 type-caption text-warning">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-pill bg-warning" />clip {r.clip.replace(/_D$/, '').slice(-4)}
                  <Tooltip label={`stop this worker (pid ${r.pid})`}><Button variant="ghost" className="ml-1" aria-label={`stop this worker (pid ${r.pid})`} onClick={() => api.stop(folder, r.pid)}>×</Button></Tooltip>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
      {cov && !cov.complete && (
        <details className="mt-3 type-body-sm">
          <summary className="cursor-pointer">Data missing: {cov.missing.length} item{cov.missing.length === 1 ? '' : 's'} · blocks {Object.keys(cov.blocked).length} decision{Object.keys(cov.blocked).length === 1 ? '' : 's'}</summary>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">{Object.entries(cov.blocked).map(([d, cs]) => <li key={d}>{d}: {cs.length} clip{cs.length === 1 ? '' : 's'}</li>)}</ul>
        </details>
      )}
      {!!p.needs?.length && <p className="mt-3 type-body-sm text-muted-foreground">To do: {p.needs.map(n => NEEDS[n] ?? n).join(', ')}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 type-body-sm">
        {p.state === 'complete' && <Button variant="default" onClick={onResults}>Go to results and export</Button>}
        {p.state !== 'complete' && !p.workers && (p.runnable ?? 0) > 0 && <Button variant="default" onClick={() => api.run(folder)}>Start processing</Button>}
        {!!p.workers && (
          <span className="text-muted-foreground">
            {p.workers} worker{p.workers === 1 ? '' : 's'} running at the lowest priority
            {(p.runnable ?? 0) === 0 ? ' · nothing else can start yet (waiting for the running stages)' : !p.can_add_worker ? ` · no more for now: ${p.add_worker_reason}` : ''}
          </span>
        )}
        {!!p.workers && !!p.can_add_worker && (p.runnable ?? 0) > 0 && (
          <Button onClick={() => api.run(folder)}>Add a worker ({p.runnable} items waiting)</Button>
        )}
        {!!p.workers && <Button onClick={() => api.stop(folder)}>Stop all</Button>}
        <Button variant="link" className="ml-auto" onClick={() => setRedo(null)}>Reprocess…</Button>
      </div>
      {redo !== undefined && <RedoDialog folder={folder} stage={redo ?? undefined} onClose={() => setRedo(undefined)} />}
      <pre className="mt-3 max-h-44 overflow-auto rounded-surface border border-border bg-card p-2 type-caption whitespace-pre-wrap">{(log?.lines ?? []).join('\n')}</pre>
    </div>
  )
}
