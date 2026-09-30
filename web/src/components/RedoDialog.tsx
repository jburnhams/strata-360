import { useEffect, useMemo, useState } from 'react'
import { api, type ItemStatus, type StateMatrix } from '../api'

const DOT: Record<string, string> = { ok: 'bg-emerald-600', failed: 'bg-red-600', active: 'bg-amber-500', stale: 'bg-amber-400', none: 'bg-stone-300 dark:bg-stone-700' }
const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').replace(/^(\d{8})(\d{6})_/, (_, d, t) => `${d.slice(6)}/${d.slice(4, 6)} ${t.slice(0, 2)}:${t.slice(2, 4)} · `)

// Choose exactly which (clip, stage) results to forget so they are processed again. Opened for a stage (all clips pre-selected, plus the stages that depend on it) or for one clip.
export default function RedoDialog({ folder, stage, clip, onClose }: { folder: string; stage?: string; clip?: string; onClose: () => void }) {
  const [m, setM] = useState<StateMatrix>()
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [cascade, setCascade] = useState(true)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.state(folder).then(x => { setM(x); if (stage) setSel(new Set(Object.keys(x.clips).filter(c => !clip || c === clip).flatMap(c => x.dependents[stage].map(s => `${c}|${s}`)))) }) }, [folder, stage, clip])
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
      <div className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-xl bg-white p-4 shadow-xl dark:bg-stone-900" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-semibold">Reprocess{stage ? `: ${stage}` : ''}{clip ? ` · ${short(clip)}` : ''}</h3>
        <p className="mb-3 text-sm text-stone-500">Ticked results are forgotten and processed again by the next worker. Files stay until they are replaced.</p>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <button className="underline" onClick={all}>select all</button><button className="underline" onClick={() => setSel(new Set())}>select none</button>
          <label className="flex items-center gap-1"><input type="checkbox" checked={cascade} onChange={e => setCascade(e.target.checked)} />also the stages that depend on the one I tick</label>
          <span className="ml-auto text-stone-500">{sel.size} selected</span>
        </div>
        <div className="overflow-auto rounded-lg border border-stone-200 dark:border-stone-800">
          <table className="w-full text-xs">
            <thead><tr><th className="sticky left-0 bg-white p-1 text-left dark:bg-stone-900">clip</th>{m.stages.map(s => (
              <th key={s} className="p-1 font-normal"><button className="underline" title="tick or untick this stage for every clip" onClick={() => toggle(rows.map(c => key(c, s)), !rows.every(c => sel.has(key(c, s))))}>{s}</button></th>))}</tr></thead>
            <tbody>{rows.map(c => (
              <tr key={c} className="border-t border-stone-200 dark:border-stone-800">
                <td className="sticky left-0 whitespace-nowrap bg-white p-1 dark:bg-stone-900"><button className="underline" onClick={() => toggle(m.stages.map(s => key(c, s)), !m.stages.every(s => sel.has(key(c, s))))}>{short(c)}</button></td>
                {m.stages.map(s => { const st = (m.clips[c][s] ?? 'none') as ItemStatus | 'none'; return (
                  <td key={s} className="p-1 text-center"><label className="inline-flex cursor-pointer items-center gap-1" title={`${s}: ${st ?? 'not done'}`}>
                    <input type="checkbox" checked={sel.has(key(c, s))} onChange={() => click(c, s)} /><span className={`h-2 w-2 rounded-full ${DOT[st ?? 'none']}`} /></label></td>) })}
              </tr>))}</tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-stone-500"><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-600" />done <span className="mx-1 inline-block h-2 w-2 rounded-full bg-amber-500" />running <span className="mx-1 inline-block h-2 w-2 rounded-full bg-amber-400" />out of date <span className="mx-1 inline-block h-2 w-2 rounded-full bg-red-600" />failed <span className="mx-1 inline-block h-2 w-2 rounded-full bg-stone-300" />not done</p>
        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded-lg border border-stone-300 px-4 py-2 dark:border-stone-700" onClick={onClose}>Cancel</button>
          <button disabled={!sel.size || busy} className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-40" onClick={go}>Clear {sel.size} item{sel.size === 1 ? '' : 's'} and reprocess</button>
        </div>
      </div>
    </div>
  )
}
