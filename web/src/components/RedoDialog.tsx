import { useEffect, useMemo, useState } from 'react'
import { api, type ItemStatus, type StateMatrix } from '../api'
import { Button, Tooltip } from 'strata-react'

const DOT: Record<string, string> = { ok: 'bg-primary', failed: 'bg-danger', active: 'bg-warning', stale: 'bg-warning', none: 'bg-neutral-4' }
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)

// Choose exactly which (clip, stage) results to forget so they are processed again. Opened for a stage (all clips pre-selected, plus the stages that depend on it) or for one clip.
export default function RedoDialog({ folder, stage, clip, onClose }: { folder: string; stage?: string; clip?: string; onClose: () => void }) {
  const [m, setM] = useState<StateMatrix>()
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [cascade, setCascade] = useState(true)
  const [busy, setBusy] = useState(false)
  useEffect(() => { let live = true; api.state(folder).then(x => { if (!live) return; setM(x); if (stage) setSel(new Set(Object.keys(x.clips).filter(c => !clip || c === clip).flatMap(c => x.dependents[stage].map(s => `${c}|${s}`)))) }).catch(() => {}); return () => { live = false } }, [folder, stage, clip])
  const rows = useMemo(() => (m ? Object.keys(m.clips).filter(c => !clip || c === clip) : []), [m, clip])
  if (!m) return null
  const key = (c: string, s: string) => `${c}|${s}`
  const toggle = (ks: string[], on: boolean) => setSel(prev => { const n = new Set(prev); ks.forEach(k => (on ? n.add(k) : n.delete(k))); return n })
  const click = (c: string, s: string) => {
    const on = !sel.has(key(c, s)); const ks = [key(c, s)]
    if (on && cascade) m.dependents[s].forEach(d => ks.push(key(c, d)))
    if (!on && cascade) m.dependents[s].forEach(d => ks.push(key(c, d)))
    toggle(ks, on)
  }
  const all = () => setSel(new Set(rows.flatMap(c => m.stages.map(s => key(c, s)))))
  const go = async () => { setBusy(true); await api.clear(folder, [...sel].map(k => { const [c, s] = k.split('|'); return { clip: c, stage: s } })); onClose() }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-overlay bg-card p-4 shadow-overlay" onClick={e => e.stopPropagation()}>
        <h3 className="type-heading font-semibold">Reprocess{stage ? `: ${stage}` : ''}{clip ? ` · ${short(clip)}` : ''}</h3>
        <p className="mb-3 type-body-sm text-muted-foreground">Ticked results are forgotten and processed again by the next worker. Files stay until they are replaced.</p>
        <div className="mb-3 flex flex-wrap items-center gap-3 type-body-sm">
          <Button variant="link" onClick={all}>select all</Button><Button variant="link" onClick={() => setSel(new Set())}>select none</Button>
          <label className="flex items-center gap-1"><input type="checkbox" checked={cascade} onChange={e => setCascade(e.target.checked)} />also the stages that depend on the one I tick</label>
          <span className="ml-auto text-muted-foreground">{sel.size} selected</span>
        </div>
        <div className="overflow-auto rounded-surface border border-border">
          <table className="w-full type-caption">
            <thead><tr><th className="sticky left-0 bg-card p-1 text-left">clip</th>{m.stages.map(s => (
              <th key={s} className="p-1 font-normal"><Tooltip label="tick or untick this stage for every clip"><Button variant="link" onClick={() => toggle(rows.map(c => key(c, s)), !rows.every(c => sel.has(key(c, s))))}>{s}</Button></Tooltip></th>))}</tr></thead>
            <tbody>{rows.map(c => (
              <tr key={c} className="border-t border-border">
                <td className="sticky left-0 whitespace-nowrap bg-card p-1"><Button variant="link" onClick={() => toggle(m.stages.map(s => key(c, s)), !m.stages.every(s => sel.has(key(c, s))))}>{short(c)}</Button></td>
                {m.stages.map(s => { const st = (m.clips[c][s] ?? 'none') as ItemStatus | 'none'; return (
                  <td key={s} className="p-1 text-center"><label className="inline-flex cursor-pointer items-center gap-1" title={`${s}: ${st ?? 'not done'}`}>
                    <input type="checkbox" checked={sel.has(key(c, s))} onChange={() => click(c, s)} /><span className={`h-2 w-2 rounded-pill ${DOT[st ?? 'none']}`} /></label></td>) })}
              </tr>))}</tbody>
          </table>
        </div>
        <p className="mt-2 type-caption text-muted-foreground"><span className="mr-1 inline-block h-2 w-2 rounded-pill bg-primary" />done <span className="mx-1 inline-block h-2 w-2 rounded-pill bg-warning" />running <span className="mx-1 inline-block h-2 w-2 rounded-pill bg-warning" />out of date <span className="mx-1 inline-block h-2 w-2 rounded-pill bg-danger" />failed <span className="mx-1 inline-block h-2 w-2 rounded-pill bg-neutral-4" />not done</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="default" disabled={!sel.size || busy} onClick={go}>Clear {sel.size} item{sel.size === 1 ? '' : 's'} and reprocess</Button>
        </div>
      </div>
    </div>
  )
}
