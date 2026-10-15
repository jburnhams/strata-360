import { useEffect, useState } from 'react'
import { api, type PaletteSchemes, type TypoFont, type TypoScheme, type Typography } from '../api'
import { PanelSkeleton } from './Skeleton'

// The look of the film's titles: its colour schemes (a few, shared by the clips) and its typography (one font for each role), both chosen from the film's vibes. The script writer proposes the vibes with its draft; your own choice replaces them.
const ROLES: { id: string; name: string; hint: string; sample: string }[] = [
  { id: 'display', name: 'Display', hint: 'the big word of a card', sample: 'DAY 2' },
  { id: 'subtitle', name: 'Subtitle', hint: 'the second line', sample: 'KILOMETRE 84' },
  { id: 'meta', name: 'Meta', hint: 'small lines: times, places', sample: 'SUN 06:38' },
  { id: 'numerals', name: 'Numerals', hint: 'figures: kilometres, pace, clocks', sample: '3:45:12' },
  { id: 'quote', name: 'Quote', hint: 'words someone said', sample: 'Keep going' },
]
const BASIS: Record<TypoScheme['basis'], string> = { user: 'your choice', script: "chosen by the script writer", project: 'worked out from the project (colours, title and notes)' }

export default function StylePanel({ folder }: { folder: string }) {
  const [data, setData] = useState<Typography | null | undefined>(undefined)       // undefined: loading, null: could not load
  const [schemes, setSchemes] = useState<PaletteSchemes>()
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string>(); const [open, setOpen] = useState<string | null>(null)
  useEffect(() => {
    let live = true; setData(undefined); setErr(undefined); setOpen(null)
    api.typography(folder).then(d => live && setData(d)).catch(() => live && setData(null)); api.paletteSchemes(folder).then(d => live && setSchemes(d)).catch(() => {})
    return () => { live = false }
  }, [folder])
  if (data === undefined) return <PanelSkeleton title="Look and feel" rows={5} />
  if (data === null) return <section className="rounded-xl border border-stone-200 bg-white p-4 text-sm text-stone-500 dark:border-stone-800 dark:bg-stone-900"><b className="text-stone-900 dark:text-stone-100">Look and feel</b><p className="mt-1">The typography could not be loaded.</p></section>
  const { scheme, library, vibes, script_vibes } = data; const base = schemes?.schemes?.[0]?.base ?? '#e7e5e4'
  const apply = async (body: Parameters<typeof api.setTypography>[1]) => {
    setBusy(true); setErr(undefined)
    try { const r = await api.setTypography(folder, body); setData(d => (d ? { ...d, scheme: r.scheme } : d)) } catch (e) { setErr(e instanceof Error ? e.message : 'That did not work.') } finally { setBusy(false) }
  }
  const picked = scheme.basis === 'user' ? scheme.style : scheme.basis === 'script' ? scheme.sources.script : Object.keys(scheme.vibes).slice(0, 5)
  const toggle = (v: string) => void apply({ style: picked.includes(v) ? picked.filter(x => x !== v) : [...picked, v] })
  const suits = (f: TypoFont, role: string) => f.roles.includes(role)

  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-lg font-semibold">Look and feel</h2><span className="text-xs text-stone-500">{scheme.families.join(' · ')}</span></div>

      <h3 className="mt-3 text-sm font-semibold">Colour schemes</h3>
      {schemes?.present && schemes.schemes?.length
        ? <ul className="mt-1 flex flex-wrap gap-3" aria-label="Colour schemes">{schemes.schemes.map(s => (
          <li key={s.label} className="rounded-lg border border-stone-200 p-2 text-xs dark:border-stone-700">
            <div className="flex gap-1">{[s.base, s.accent, s.support, s.light, s.dark].map((c, i) => <span key={i} title={c} className="h-6 w-6 rounded border border-stone-300 dark:border-stone-600" style={{ background: c }} />)}</div>
            <div className="mt-1"><b>{s.label}</b> · {s.clips} {s.clips === 1 ? 'clip' : 'clips'}</div></li>))}</ul>
        : <p className="mt-1 text-xs text-stone-500">No colour schemes yet: run the palette stage on the clips, then <code>strata360 palette-schemes</code>.</p>}

      <h3 className="mt-4 text-sm font-semibold">Vibes <span className="font-normal text-stone-500">· {BASIS[scheme.basis]}</span></h3>
      <p className="text-xs text-stone-500">How the film should feel. They choose the fonts below{script_vibes.length ? `; the script writer proposed ${script_vibes.join(', ')}` : ' (the script writer proposes some with its draft)'}. Pick your own to override.</p>
      <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Vibes">{vibes.map(v => {
        const on = picked.includes(v)
        return <li key={v}><button aria-pressed={on} disabled={busy} onClick={() => toggle(v)} title={scheme.vibes[v] ? `weight ${scheme.vibes[v].toFixed(2)}` : undefined}
          className={`rounded-full border px-3 py-1 text-xs ${on ? 'border-emerald-700 bg-emerald-700 text-white' : 'border-stone-300 hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800'} disabled:opacity-50`}>{v}</button></li>
      })}</ul>
      {scheme.basis === 'user' && <button disabled={busy} onClick={() => void apply({ style: [] })} className="mt-2 text-xs text-emerald-700 underline dark:text-emerald-400">{script_vibes.length ? `Use the script writer's choice again (${script_vibes.join(', ')})` : 'Clear my choice'}</button>}

      <h3 className="mt-4 text-sm font-semibold">Typography</h3>
      <ul className="mt-2 grid gap-3 md:grid-cols-2" aria-label="Fonts by role">{ROLES.map(r => {
        const fid = scheme.fonts[r.id]; const f = library.find(x => x.id === fid); const mine = scheme.overrides[r.id] === fid
        return (
          <li key={r.id} className="rounded-lg border border-stone-200 p-3 dark:border-stone-700">
            <div className="flex items-baseline justify-between gap-2 text-xs"><h4 className="text-sm font-semibold">{r.name}</h4><span className="text-stone-500">{r.hint}</span></div>
            <div className="mt-2 grid min-h-[5rem] place-items-center rounded-md bg-stone-900 p-3"><img src={api.typoSample(fid, r.sample, 72, base)} alt={`${r.sample} in ${f?.family ?? fid}`} className="max-h-20 max-w-full" /></div>
            <div className="mt-2 text-sm"><b>{f?.family ?? fid}</b> <span className="text-xs text-stone-500">{mine ? 'chosen by you' : 'chosen for the vibes'}</span></div>
            <p className="text-xs text-stone-500">{scheme.why[r.id]}</p>
            <div className="mt-2 flex gap-3 text-xs">
              <button onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id} className="text-emerald-700 underline dark:text-emerald-400">{open === r.id ? 'Close' : 'Change font'}</button>
              {scheme.overrides[r.id] && <button disabled={busy} onClick={() => void apply({ fonts: { [r.id]: null } })} className="text-emerald-700 underline dark:text-emerald-400">Back to automatic</button>}
            </div>
            {open === r.id && <div className="mt-2" role="group" aria-label={`Fonts for ${r.name}`}>
              {[true, false].map(fit => {
                const list = library.filter(x => suits(x, r.id) === fit); if (!list.length) return null
                return <div key={String(fit)} className="mb-2"><p className="mb-1 text-xs text-stone-500">{fit ? 'Designed for this role' : 'Not designed for this role (can look wrong)'}</p>
                  <ul className="grid grid-cols-2 gap-2">{list.map(x => (
                    <li key={x.id}><button disabled={busy} onClick={() => { void apply({ fonts: { [r.id]: x.id } }); setOpen(null) }} aria-pressed={x.id === fid} title={`${x.desc}. Vibes: ${x.vibes.join(', ')}`}
                      className={`w-full rounded-md border p-2 text-left text-xs ${x.id === fid ? 'border-emerald-700 ring-1 ring-emerald-700' : 'border-stone-300 hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800'}`}>
                      <span className="grid h-10 place-items-center rounded bg-stone-900"><img src={api.typoSample(x.id, r.sample, 40, base)} alt="" className="max-h-9 max-w-full" /></span><span className="mt-1 block truncate">{x.family}</span></button></li>))}</ul></div>
              })}</div>}
          </li>)
      })}</ul>
      {err && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-400">{err}</p>}
      <p className="mt-3 text-xs text-stone-500">Used by the film's text cards, and the opening and ending titles. Your choices are kept; a new script draft changes only what you have not chosen.</p>
    </section>
  )
}
