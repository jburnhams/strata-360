import { useEffect, useState } from 'react'
import { api, type OverlaySettings as Settings, type OverlayState } from '../api'

const STYLE_LABEL: Record<string, string> = { 'tf-outdoors': 'Outdoors (contours, paths)', 'tf-landscape': 'Landscape (towns, relief)', 'tf-cycle': 'Cycle', 'tf-transport': 'Transport', 'tf-atlas': 'Atlas', osm: 'OpenStreetMap (no key)' }
const styleLabel = (s: { name: string; needs_key: boolean }) => STYLE_LABEL[s.name] ?? s.name

// The race overlay on the final film (race.json `overlay`): on or off, which elements, the two maps' styles and the close-up's zoom, and the map key (write-only: stored on the server, never shown again).
export default function OverlaySettings({ folder, disabled = false }: { folder: string; disabled?: boolean }) {
  const [st, setSt] = useState<OverlayState>(), [draft, setDraft] = useState<Settings>(), [err, setErr] = useState(''), [saving, setSaving] = useState(false), [saved, setSaved] = useState(false), [key, setKey] = useState('')
  useEffect(() => {
    let live = true; setSt(undefined); setDraft(undefined); setErr('')
    api.overlay(folder).then(s => { if (live) { setSt(s); setDraft(s.settings) } }, e => live && setErr(String(e.message ?? e)))
    return () => { live = false }
  }, [folder])
  if (!st || !draft) return err ? <p className="mt-3 type-body-sm text-danger">Overlay settings: {err}</p> : null
  const set = (o: Partial<Settings>) => { setDraft({ ...draft, ...o }); setSaved(false) }
  const changed = JSON.stringify(draft) !== JSON.stringify(st.settings)
  const run = async (f: () => Promise<OverlayState | void>) => {
    setSaving(true); setErr('')
    try { const s = await f(); if (s) { setSt(s); setDraft(s.settings); setSaved(true) } } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setSaving(false) }
  }
  const saveKey = (k: string) => run(async () => { const r = await api.setMapKey(k); setKey(''); setSt({ ...st, key_set: r.key_set }) })
  const keyNeeded = st.styles.some(s => s.needs_key && (s.name === draft.route_style || s.name === draft.local_style))
  const sel = 'rounded-surface border border-border bg-card px-2 py-1 type-body-sm'
  const map = (label: string, k: 'route_style' | 'local_style') => (
    <label className="type-body-sm">{label} <select className={sel} value={draft[k]} onChange={e => set({ [k]: e.target.value })}>{st.styles.map(s => <option key={s.name} value={s.name}>{styleLabel(s)}</option>)}</select></label>)
  return (
    <details className="mt-3 rounded-surface border border-border p-3">
      <summary className="cursor-pointer type-body-sm font-medium">Overlay <span className="font-normal text-muted-foreground">· {draft.enabled ? `${draft.elements.length} elements` : 'off'}{keyNeeded && !st.key_set ? ' · map key missing' : ''}</span></summary>
      <fieldset disabled={disabled || saving} className="mt-3 space-y-3">
        <legend className="sr-only">Overlay settings</legend>
        <label className="block type-body-sm"><input type="checkbox" checked={draft.enabled} onChange={e => set({ enabled: e.target.checked })} /> Draw the race overlay on the film</label>
        <div role="group" aria-label="Elements" className="flex flex-wrap gap-x-4 gap-y-1">
          {st.elements.map(e => <label key={e.name} className="type-body-sm"><input type="checkbox" checked={draft.elements.includes(e.name)} disabled={!draft.enabled} onChange={ev => set({ elements: st.elements.map(x => x.name).filter(x => x === e.name ? ev.target.checked : draft.elements.includes(x)) })} /> {e.label}</label>)}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {map('Whole-route map style', 'route_style')}
          {map('Close-up map style', 'local_style')}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="type-body-sm">Close-up zoom <input type="number" className={sel + ' w-20'} min={st.zoom_min} max={st.zoom_max} step={0.5} value={draft.local_zoom} onChange={e => set({ local_zoom: Number(e.target.value) })} /></label>
          <label className="type-body-sm" title="The close-up zooms in where the map is busy and out on straight stretches, within this many levels of the zoom above."><input type="checkbox" checked={draft.auto_zoom} onChange={e => set({ auto_zoom: e.target.checked })} /> Zoom by itself</label>
          <label className="type-body-sm">by up to <input type="number" className={sel + ' w-20'} min={0} max={4} step={0.5} value={draft.zoom_range} disabled={!draft.auto_zoom} onChange={e => set({ zoom_range: Number(e.target.value) })} /> levels</label>
        </div>
        <div className="flex items-center gap-3">
          <button className="rounded-surface bg-neutral-11 px-3 py-1.5 type-body-sm text-white disabled:opacity-50" disabled={!changed} onClick={() => run(() => api.saveOverlay(folder, draft))}>Save overlay settings</button>
          {changed && <button className="type-body-sm underline" onClick={() => setDraft(st.settings)}>undo changes</button>}
          {saved && !changed && <span className="type-body-sm text-primary">saved; the overlay thumbnails are being made again</span>}
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
          <span className="type-body-sm">Map key (Thunderforest): {st.key_set ? <span className="text-primary">set</span> : <span className={keyNeeded ? 'text-danger' : 'text-muted-foreground'}>not set{keyNeeded ? ', the maps need it' : ''}</span>}</span>
          <label className="type-body-sm"><span className="sr-only">Map key</span><input type="password" autoComplete="off" placeholder={st.key_set ? 'replace the key' : 'paste the key'} className={sel} value={key} onChange={e => setKey(e.target.value)} /></label>
          <button className="rounded-surface border border-border px-2 py-1 type-body-sm disabled:opacity-50" disabled={!key.trim()} onClick={() => saveKey(key)}>Save key</button>
          {st.key_set && <button className="type-body-sm underline" onClick={() => saveKey('')}>remove key</button>}
          <span className="type-caption text-muted-foreground">{st.tiles_cached} map tiles cached. The key is kept in secrets.env on this computer and never shown again.</span>
        </div>
        {err && <p className="type-body-sm text-danger">{err}</p>}
      </fieldset>
    </details>
  )
}
