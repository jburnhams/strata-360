import { useState, type RefObject } from 'react'
import { api, type FilmTextState, type TextCard, type TextCardEdit, type TextElement } from '../api'
import { clock } from './stillModes'

// The film's on-screen text (the word-art cards): each one listed under the preview with when it is, what it says and why, a picture of it on the film's frame and the words by themselves. Click the time to
// play the film from there. A card can be changed or deleted, and a new one made at the player's position. A save draws its pictures again; "Preview" draws them again on demand.
const field = 'rounded border border-stone-300 bg-stone-50 px-1.5 py-0.5 text-sm dark:border-stone-700 dark:bg-stone-950'
const small = 'rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-700'

type Draft = { id?: string; t: number; dur_s: number; start_s: number; elements: TextElement[]; texts: string[] }

const toDraft = (c: TextCard): Draft => ({ id: c.id, t: c.t, dur_s: c.dur_s, start_s: c.start_s, elements: c.elements.map(e => ({ ...e, fill: { ...e.fill } })), texts: [] })

export default function FilmText({ folder, video, list, reload }: { folder: string; video: RefObject<HTMLVideoElement | null>; list?: FilmTextState; reload: () => void }) {
  const [shown, setShown] = useState<Record<string, number>>({}), [draft, setDraft] = useState<Draft | null>(null), [err, setErr] = useState<string>(), [busy, setBusy] = useState(false), [note, setNote] = useState<string>()
  if (!list) return null
  const now = () => Math.round((video.current?.currentTime ?? 0) * 10) / 10
  const go = (t: number) => { const v = video.current; if (!v) return; v.currentTime = t; v.scrollIntoView?.({ block: 'nearest' }); void v.play?.()?.catch?.(() => {}) }
  const redraw = (id: string) => setShown(s => ({ ...s, [id]: (s[id] ?? 0) + 1 }))
  const fail = (e: unknown) => { setErr(e instanceof Error ? e.message : String(e)); setBusy(false) }
  const save = () => {
    if (!draft) return
    setErr(undefined); setBusy(true)
    const card: TextCardEdit = draft.id ? { id: draft.id, t: draft.t, dur_s: draft.dur_s, start_s: draft.start_s, elements: draft.elements } : { t: draft.t, dur_s: draft.dur_s, start_s: draft.start_s, texts: draft.texts.filter(x => x.trim()) }
    api.saveFilmText(folder, card).then(c => { setBusy(false); setDraft(null); setNote(`Saved ${c.lines.map(l => l.text).join(' / ')}`); redraw(c.id); reload() }).catch(fail)
  }
  const remove = (c: TextCard) => {
    if (!window.confirm(`Delete the text “${c.lines.map(l => l.text).join(' / ')}” at ${clock(c.t)}?`)) return
    setErr(undefined); api.deleteFilmText(folder, c.id).then(() => { setNote('Deleted'); reload() }).catch(fail)
  }
  const edit = (patch: Partial<Draft>) => setDraft(d => d && { ...d, ...patch })
  const editEl = (i: number, patch: Partial<TextElement>) => setDraft(d => d && { ...d, elements: d.elements.map((e, k) => k === i ? { ...e, ...patch } : e) })
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-3">
        <h4 className="text-sm font-semibold">On-screen text</h4>
        <span className="text-sm text-stone-500">{list.cards.length} {list.cards.length === 1 ? 'card' : 'cards'}</span>
        <button className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white" onClick={() => { setErr(undefined); setNote(undefined); setDraft({ t: now(), dur_s: 3, start_s: 0.15, elements: [], texts: ['', ''] }) }}>Add text at the player position</button>
        {note && <span className="text-sm text-emerald-700" role="status">{note}</span>}
        {err && <span className="text-sm text-red-600" role="alert">{err}</span>}
      </div>
      {list.stale && <p className="mt-1 text-sm text-amber-700" role="status">These cards were made for an earlier plan, so the times may no longer suit the film. They are not drawn in the film until the text is made again (<code>strata360 filmtext</code>) or you save them here.</p>}
      {!list.has_preview && <p className="mt-1 text-sm text-stone-500">Render the film preview to see each card on its frame.</p>}
      {draft && !draft.id && <Editor key="new" list={list} draft={draft} busy={busy} now={now} edit={edit} editEl={editEl} save={save} cancel={() => setDraft(null)} />}
      {!list.cards.length && !draft && <p className="mt-2 text-sm text-stone-500">No on-screen text yet. Add some here, or let the local models suggest it (<code>strata360 filmtext</code>).</p>}
      <ul className="mt-2 flex max-w-5xl flex-col gap-3">
        {list.cards.map(c => {
          const v = shown[c.id] ?? 0, words = c.lines.map(l => l.text).join(' / '), editing = draft?.id === c.id
          return (
            <li key={c.id} className="rounded-lg border border-stone-200 p-3 dark:border-stone-800">
              <div className="flex flex-wrap items-center gap-2">
                <button className="rounded-lg bg-stone-800 px-2 py-1 text-sm tabular-nums text-white dark:bg-stone-200 dark:text-stone-900" onClick={() => go(c.t)} aria-label={`Play the film from ${clock(c.t)}`}>▶ {clock(c.t)}</button>
                <span className="text-sm font-medium">{words}</span>
                <span className="text-xs text-stone-500">{c.type}{c.user ? ' · by hand' : ''} · {c.dur_s.toFixed(1)} s</span>
                {c.score != null && <span className="text-xs text-stone-500" title={c.worth_why}>score {c.score.toFixed(1)}</span>}
                {c.blocking && <span className={`text-xs ${c.blocking.score >= 3 ? 'text-amber-700' : 'text-stone-500'}`} title={c.blocking.what || 'nothing covered'}>blocks {c.blocking.score.toFixed(1)}{c.blocking.what ? ` (${c.blocking.what})` : ''}</span>}
                <span className="ml-auto flex gap-2">
                  <button className={small} onClick={() => redraw(c.id)} aria-label={`Preview ${words}`}>Preview</button>
                  <button className={small} onClick={() => { setErr(undefined); setNote(undefined); setDraft(editing ? null : toDraft(c)) }} aria-label={`Edit ${words}`}>{editing ? 'Close' : 'Edit'}</button>
                  <button className={`${small} text-red-700`} onClick={() => remove(c)} aria-label={`Delete ${words}`}>Delete</button>
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-3">
                <Picture src={api.filmTextStillUrl(folder, c.id, 'still', v)} label={`${words} on the film`} />
                <Picture src={api.filmTextStillUrl(folder, c.id, 'text', v)} label={`${words} by itself`} />
                <div className="min-w-48 max-w-md flex-1 text-xs text-stone-600 dark:text-stone-400">
                  {c.why && <p className="mb-1">{c.why}</p>}
                  {c.shot && <p className="mb-1">Shot: {c.shot.verdict}, excitement {c.shot.excitement}, risk of covering something {c.shot.obscure_risk}{c.shot.why ? `. ${c.shot.why}` : ''}</p>}
                  {c.worth_why && <p>Why this text: {c.worth_why}</p>}
                </div>
              </div>
              {editing && draft && <Editor list={list} draft={draft} busy={busy} now={now} edit={edit} editEl={editEl} save={save} cancel={() => setDraft(null)} />}
            </li>
          )
        })}
      </ul>
      <p className="mt-2 max-w-3xl text-xs text-stone-500">The pictures are drawn at once, on every save and with Preview. Over the preview film the cards are drawn live from what is saved here (drag a word on the picture to move it); the final film shows a change when it is rendered again, and only the pieces the change touches are made again.</p>
    </div>
  )
}

function Picture({ src, label }: { src: string; label: string }) {
  const [bad, setBad] = useState(false)
  return bad
    ? <div className="flex aspect-video w-64 items-center justify-center rounded border border-dashed border-stone-300 p-2 text-center text-xs text-stone-500 dark:border-stone-700">{label}: no picture yet (render the preview)</div>
    : <img src={src} alt={label} loading="lazy" className="aspect-video w-64 rounded border border-stone-200 bg-stone-100 object-contain dark:border-stone-800" onError={() => setBad(true)} onLoad={() => setBad(false)} key={src} />
}

function Editor({ list, draft, busy, now, edit, editEl, save, cancel }: { list: FilmTextState; draft: Draft; busy: boolean; now: () => number; edit: (p: Partial<Draft>) => void; editEl: (i: number, p: Partial<TextElement>) => void; save: () => void; cancel: () => void }) {
  const num = (v: string, d: number) => { const n = parseFloat(v); return Number.isFinite(n) ? n : d }
  return (
    <form className="mt-3 flex flex-col gap-3 rounded-lg bg-stone-50 p-3 dark:bg-stone-900" aria-label={draft.id ? 'Edit text' : 'New text'} onSubmit={e => { e.preventDefault(); save() }}>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">Starts at (s)<input className={`${field} ml-2 w-24`} type="number" step="0.1" min="0" max={list.length_s || undefined} value={draft.t} onChange={e => edit({ t: num(e.target.value, draft.t) })} /></label>
        <button type="button" className={small} onClick={() => edit({ t: now() })}>Use player position</button>
        <label className="text-sm">Lasts (s)<input className={`${field} ml-2 w-20`} type="number" step="0.1" min="0.8" max="20" value={draft.dur_s} onChange={e => edit({ dur_s: num(e.target.value, draft.dur_s) })} /></label>
        <label className="text-sm" title="How long after the card starts the first word appears">Delay (s)<input className={`${field} ml-2 w-20`} type="number" step="0.05" min="0" value={draft.start_s} onChange={e => edit({ start_s: num(e.target.value, draft.start_s) })} /></label>
      </div>
      {!draft.id
        ? <div className="flex flex-col gap-2">{draft.texts.map((t, i) => <label key={i} className="text-sm">{i === 0 ? 'Words' : 'Smaller line'}<input className={`${field} ml-2 w-72`} value={t} placeholder={i === 0 ? 'HALFWAY' : 'optional'} onChange={e => edit({ texts: draft.texts.map((x, k) => k === i ? e.target.value : x) })} /></label>)}</div>
        : draft.elements.map((e, i) => (
          <fieldset key={i} className="flex flex-wrap items-end gap-3 rounded border border-stone-200 p-2 dark:border-stone-800">
            <legend className="px-1 text-xs text-stone-500">Word {i + 1}</legend>
            <label className="text-sm">Text<input className={`${field} ml-2 w-56`} value={e.text} onChange={ev => editEl(i, { text: ev.target.value })} /></label>
            <label className="text-sm">Font<select className={`${field} ml-2`} value={e.font} onChange={ev => editEl(i, { font: ev.target.value })}>{list.fonts.map(f => <option key={f.id} value={f.id} title={f.note}>{f.id}</option>)}</select></label>
            <label className="text-sm">Size<input className={`${field} ml-2 w-20`} type="number" step="0.01" min="0.03" max="0.42" value={e.size} onChange={ev => editEl(i, { size: num(ev.target.value, e.size) })} /></label>
            <label className="text-sm">Across<input className={`${field} ml-2 w-20`} type="number" step="0.01" min="0.06" max="0.94" value={Math.round(e.x * 1000) / 1000} onChange={ev => editEl(i, { x: num(ev.target.value, e.x) })} /></label>
            <label className="text-sm">Down<input className={`${field} ml-2 w-20`} type="number" step="0.01" min="0.08" max="0.92" value={Math.round(e.y * 1000) / 1000} onChange={ev => editEl(i, { y: num(ev.target.value, e.y) })} /></label>
            <label className="text-sm">Turn (°)<input className={`${field} ml-2 w-20`} type="number" step="1" value={e.rot} onChange={ev => editEl(i, { rot: num(ev.target.value, e.rot) })} /></label>
            <label className="text-sm">Colour<input className="ml-2 h-7 w-10 align-middle" type="color" value={/^#[0-9a-f]{6}$/i.test(e.fill.c1) ? e.fill.c1 : '#ffffff'} onChange={ev => editEl(i, { fill: { ...e.fill, type: 'solid', c1: ev.target.value, c2: ev.target.value } })} /></label>
            <label className="text-sm">In<select className={`${field} ml-2`} value={e.in} onChange={ev => editEl(i, { in: ev.target.value })}>{list.presets_in.map(p => <option key={p}>{p}</option>)}</select></label>
            <label className="text-sm">Out<select className={`${field} ml-2`} value={e.out} onChange={ev => editEl(i, { out: ev.target.value })}>{list.presets_out.map(p => <option key={p}>{p}</option>)}</select></label>
            {draft.elements.length > 1 && <button type="button" className={`${small} text-red-700`} onClick={() => edit({ elements: draft.elements.filter((_, k) => k !== i) })}>Remove word</button>}
          </fieldset>
        ))}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy ? 'Saving…' : 'Save'}</button>
        <button type="button" className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm dark:border-stone-700" onClick={cancel}>Cancel</button>
      </div>
    </form>
  )
}
