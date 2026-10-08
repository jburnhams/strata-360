import { useEffect, useState } from 'react'
import type { RenderProgress as Progress } from '../api'

/** Seconds as "12.3 s" under a minute, "3:07" over. */
export const dur = (s: number) => s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

const BUCKETS: Record<string, string> = { decode: 'reading the video', seam: 'joining the two lenses', project: 'projecting the view', upscale: 'enlarging (model)', resample: 'resampling to the output size', grade: 'exposure match', overlay: 'drawing the overlay', encode: 'encoding' }
const MARK = { running: '●', done: '✓', error: '✗' } as const

// What a render is doing and how long each step takes: the steps in order (the running one counts up live), where the time goes inside the render, and its log. The numbers come from the render's own progress file (render/progress.py), so they are what the
// worker measured, not guesses.
export default function RenderProgress({ progress, busy }: { progress?: Progress | null; busy: boolean }) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => { if (!busy) return; const id = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(id) }, [busy])
  if (!progress) return null
  const live = (s: Progress['stages'][number]) => s.state === 'running' && busy ? Math.max(s.seconds, now - s.started) : s.seconds
  const spent = Object.values(progress.timings).reduce((a, b) => a + b.seconds, 0), rows = Object.entries(progress.timings).sort((a, b) => b[1].seconds - a[1].seconds)
  return (
    <div className="mt-2 space-y-2 text-sm" aria-label="Render progress">
      <ol className="space-y-0.5">
        {progress.stages.map((s, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-2">
            <span aria-hidden className={s.state === 'error' ? 'text-red-600' : s.state === 'running' ? 'text-amber-600' : 'text-emerald-700'}>{MARK[s.state]}</span>
            <span className="font-medium">{s.name}</span>
            {s.detail && <span className="text-xs text-stone-500">{s.detail}</span>}
            <span className="ml-auto tabular-nums text-xs text-stone-500">{dur(live(s))}</span>
          </li>
        ))}
      </ol>
      {rows.length > 0 && (
        <table className="w-full text-xs">
          <caption className="mb-0.5 text-left font-medium text-stone-600 dark:text-stone-400">Where the time goes inside the render</caption>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <th scope="row" className="w-44 pr-2 text-left font-normal">{BUCKETS[k] ?? k}</th>
                <td className="w-16 pr-2 text-right tabular-nums">{dur(v.seconds)}</td>
                <td className="w-12 pr-2 text-right tabular-nums text-stone-500">{spent ? Math.round(100 * v.seconds / spent) : 0}%</td>
                <td><div className="h-1.5 rounded bg-emerald-600/70" style={{ width: `${spent ? Math.max(2, 100 * v.seconds / spent) : 0}%` }} /></td>
                <td className="w-24 pl-2 text-right tabular-nums text-stone-500">{v.calls} {v.calls === 1 ? 'call' : 'calls'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {progress.error && <p className="text-xs text-red-600">{progress.error}</p>}
      {progress.log.length > 0 && (
        <details open={busy}>
          <summary className="cursor-pointer text-xs text-stone-500">Log ({progress.log.length} lines)</summary>
          <pre className="mt-1 max-h-40 overflow-auto rounded bg-stone-100 p-2 text-xs dark:bg-stone-950" tabIndex={0}>{progress.log.slice(-60).map(([t, m]) => `+${dur(t)}  ${m}`).join('\n')}</pre>
        </details>
      )}
    </div>
  )
}
