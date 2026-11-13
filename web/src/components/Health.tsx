import type { StageHealth } from '../api'

const ago = (s: number | null | undefined) => s == null ? 'none yet' : s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${(s / 3600).toFixed(1)} h ago`

// Items of a stage that failed for now and will be tried again: how many are failing at once, which try they are on, how long since anything of this stage last succeeded, and the last error.
export default function Health({ h, className = '' }: { h?: StageHealth | null; className?: string }) {
  if (!h || (!h.retrying && !h.failed)) return null
  return (
    <div className={`type-caption ${h.retrying ? 'text-warning' : 'text-danger'} ${className}`}>
      {h.retrying > 0 && <span title="items that failed for now and will be tried again">⟳ {h.retrying} failing now (try {h.attempts} of {h.retries})</span>}
      {h.retrying > 0 && h.next_try_in_s != null && <span title="exponential backoff: each retry waits twice as long as the one before, up to 10 minutes"> · sleeping {h.next_try_in_s === 0 ? 'done: trying now' : `${h.next_try_in_s} s left${h.sleep_s ? ` of a ${h.sleep_s} s backoff` : ''}`}</span>}
      {h.failed > 0 && <span>{h.retrying > 0 ? ' · ' : ''}{h.failed} gave up</span>}
      <span> · last success {ago(h.last_success_ago_s)}</span>
      {h.last_error && <span className="text-muted-foreground" title={h.last_error}> · {h.last_error.replace(/^.*?(HTTP \d+[^.]*).*$/s, '$1').slice(0, 110)}</span>}
    </div>
  )
}
