import { useEffect, useState } from 'react'
import type { RenderProgress as Progress } from '../api'
import { Disclosure } from 'strata-react'

/** Seconds as "12.3 s" under a minute, "3:07" over. */
export const dur = (s: number) => s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

const BUCKETS: Record<string, string> = { decode: 'reading the video', seam: 'joining the two lenses', project: 'projecting the view', upscale: 'enlarging (model)', resample: 'resampling to the output size', grade: 'exposure match', overlay: 'drawing the overlay', encode: 'encoding' }
const MARK = { running: '●', done: '✓', error: '✗' } as const

// What a render is doing and how long each step takes: the steps in order (the running one counts up live), where the time goes inside the render, and its log. The numbers come from the render's own progress file (render/progress.py), so they are what the
// worker measured, not guesses.
export default function RenderProgress({ progress, busy }: { progress?: Progress | null; busy: boolean }) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [logOpen, setLogOpen] = useState(busy)
  useEffect(() => { setLogOpen(busy) }, [busy])                                                                      // open while rendering, closed when it finishes; the person can still fold it either way
  useEffect(() => { if (!busy) return; const id = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(id) }, [busy])
  if (!progress) return null
  const live = (s: Progress['stages'][number]) => s.state === 'running' && busy ? Math.max(s.seconds, now - s.started) : s.seconds
  const spent = Object.values(progress.timings).reduce((a, b) => a + b.seconds, 0), rows = Object.entries(progress.timings).sort((a, b) => b[1].seconds - a[1].seconds)
  return (
    <div className="mt-2 space-y-2 type-body-sm" aria-label="Render progress">
      <ol className="space-y-0.5">
        {progress.stages.map((s, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-2">
            <span aria-hidden className={s.state === 'error' ? 'text-danger' : s.state === 'running' ? 'text-warning' : 'text-primary'}>{MARK[s.state]}</span>
            <span className="font-medium">{s.name}</span>
            {s.detail && <span className="type-caption text-muted-foreground">{s.detail}</span>}
            <span className="ml-auto tabular-nums type-caption text-muted-foreground">{dur(live(s))}</span>
          </li>
        ))}
      </ol>
      {rows.length > 0 && (
        <table className="w-full type-caption">
          <caption className="mb-0.5 text-left font-medium text-muted-foreground">Where the time goes inside the render</caption>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <th scope="row" className="w-44 pr-2 text-left font-normal">{BUCKETS[k] ?? k}</th>
                <td className="w-16 pr-2 text-right tabular-nums">{dur(v.seconds)}</td>
                <td className="w-12 pr-2 text-right tabular-nums text-muted-foreground">{spent ? Math.round(100 * v.seconds / spent) : 0}%</td>
                <td><div className="h-1.5 rounded-control bg-primary/70" style={{ width: `${spent ? Math.max(2, 100 * v.seconds / spent) : 0}%` }} /></td>
                <td className="w-24 pl-2 text-right tabular-nums text-muted-foreground">{v.calls} {v.calls === 1 ? 'call' : 'calls'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {progress.error && <p className="type-caption text-danger">{progress.error}</p>}
      {progress.log.length > 0 && (
        <Disclosure summary={`Log (${progress.log.length} lines)`} open={logOpen} onOpenChange={setLogOpen}>
          <pre className="mt-1 max-h-40 overflow-auto rounded-control bg-muted p-2 type-caption" tabIndex={0}>{progress.log.slice(-60).map(([t, m]) => `+${dur(t)}  ${m}`).join('\n')}</pre>
        </Disclosure>
      )}
    </div>
  )
}
