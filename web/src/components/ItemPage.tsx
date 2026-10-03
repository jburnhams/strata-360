import { useState } from 'react'
import type { GapScriptItem } from '../api'
import NoteBox from './NoteBox'

// The page of one thing the film can show that is not a camera clip: a gap, a photo or a street view section. They all have the same sections, so this is shared: the preview, how it is drawn and how long it is, what the script says over it,
// and your notes with the voice-over you want inside it. Each kind brings its own preview and its own settings.
export const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900"><h3 className="mb-2 text-sm font-semibold">{title}</h3>{children}</section>
)

export function VoiceOverCard({ items, noun, must }: { items: GapScriptItem[]; noun: string; must: boolean }) {
  return (
    <Card title="Voice-over">
      {items.length === 0 ? <p className="text-sm text-stone-500">The newest script draft does not use this {noun}{must ? ' (it is marked must-use, so the plan adds it)' : ''}.</p>
        : <ul className="space-y-1 text-sm">{items.map(it => (
          <li key={it.n}><span className="mr-2 font-mono text-xs text-stone-500">item {it.n} · {it.type}{it.seconds ? ` · ${it.seconds} s` : ''}</span>{it.text || <span className="text-stone-500">picture only</span>}</li>))}</ul>}
      <p className="mt-2 text-xs text-stone-500">Narration you want spoken inside this {noun} goes in “Voice-over MUST INCLUDE” below.</p>
    </Card>
  )
}

/** The Length field: "the plan decides", "exactly" and, where the kind supports it, "at least", with the seconds. `onChange` gets the mode ('' = the plan decides) and the seconds. */
export function LengthField({ id, mode, seconds, modes, min, max, fallback, disabled, onChange }: { id: string; mode: '' | 'set' | 'min'; seconds: number | null; modes: ('set' | 'min')[]; min: number; max: number; fallback: number; disabled?: boolean; onChange: (mode: '' | 'set' | 'min', seconds: number | null) => void }) {
  const [draft, setDraft] = useState<{ id: string; seconds: string }>()
  const text = draft?.id === id ? draft.seconds : seconds != null ? String(seconds) : ''
  const commit = () => { if (draft?.id !== id) return; const v = Number(draft.seconds); setDraft(undefined); if (Number.isFinite(v) && draft.seconds.trim() !== '' && v !== seconds) onChange(mode, v) }
  return (
    <div className="flex items-center gap-2"><span className="w-24 text-stone-500">Length</span>
      <select aria-label="Length" value={mode} disabled={disabled} onChange={e => { const m = e.target.value as '' | 'set' | 'min'; onChange(m, m ? seconds ?? fallback : null) }} className="rounded border border-stone-300 bg-transparent px-1 py-0.5 dark:border-stone-700">
        <option value="">the plan decides</option>{modes.includes('set') && <option value="set">exactly</option>}{modes.includes('min') && <option value="min">at least</option>}
      </select>
      <input aria-label="Length in seconds" type="number" min={min} max={max} step={1} disabled={!mode} value={text} onChange={e => setDraft({ id, seconds: e.target.value })} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        className="w-16 rounded border border-stone-300 bg-transparent px-1 py-0.5 disabled:opacity-40 dark:border-stone-700" /> <span className="text-xs text-stone-500">s</span></div>
  )
}

export default function ItemPage({ folder, heading, sub, err, preview, settings, help, script, noun, must, noteClip, noteTitle, notePlaceholder, more }: {
  folder: string; heading: React.ReactNode; sub?: React.ReactNode; err?: string; preview: React.ReactNode; settings: React.ReactNode; help: string; script: GapScriptItem[]; noun: string; must: boolean; noteClip: string; noteTitle: string; notePlaceholder: string; more?: React.ReactNode
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">{heading}</h2>
        {sub && <p className="text-sm text-stone-500">{sub}</p>}
      </div>
      {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
      <Card title="Preview">{preview}</Card>
      {more}
      <Card title="How it is drawn and how long it is"><div className="grid gap-3 text-sm sm:grid-cols-2">{settings}</div><p className="mt-2 text-xs text-stone-500">{help}</p></Card>
      <VoiceOverCard items={script} noun={noun} must={must} />
      <NoteBox folder={folder} clip={noteClip} title={noteTitle} placeholder={notePlaceholder} />
    </div>
  )
}
