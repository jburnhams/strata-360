import type { ScriptPins, VoPin } from './api'

// Pure helpers for the user's narration pins (the server keeps them in script2/pins.json): green text is said word for word, red text is never said.
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
const inside = (small: string, big: string) => big.toLowerCase().includes(small.trim().toLowerCase())
const nextId = (pins: ScriptPins) => { const used = new Set((pins.vo ?? []).map(p => p.id)); let n = (pins.vo ?? []).length + 1; while (used.has(`v${n}`)) n++; return `v${n}` }

/** Say this text exactly, inside that clip's run (or loosen it with setMode). The same text in the same clip is not added twice. */
export function addPin(pins: ScriptPins, text: string, clip: string, mode: VoPin['mode'] = 'clip'): ScriptPins {
  const t = text.trim(); if (!t) return pins
  if ((pins.vo ?? []).some(p => same(p.text, t) && (p.clip ?? '') === (mode === 'clip' ? clip : ''))) return pins
  return { ...pins, vo: [...(pins.vo ?? []), { id: nextId(pins), text: t, mode, ...(mode === 'clip' ? { clip } : {}) }] }
}
export const removePin = (pins: ScriptPins, id: string): ScriptPins => ({ ...pins, vo: (pins.vo ?? []).filter(p => p.id !== id) })
export const setMode = (pins: ScriptPins, id: string, mode: VoPin['mode'], clip?: string): ScriptPins =>
  ({ ...pins, vo: (pins.vo ?? []).map(p => p.id !== id ? p : mode === 'clip' ? { ...p, mode, clip: clip ?? p.clip } : { id: p.id, text: p.text, mode }) })
export function addNever(pins: ScriptPins, phrase: string): ScriptPins {
  const t = phrase.trim(); if (!t || (pins.vo_never ?? []).some(x => same(x, t))) return pins
  return { ...pins, vo_never: [...(pins.vo_never ?? []), t] }
}
export const removeNever = (pins: ScriptPins, phrase: string): ScriptPins => ({ ...pins, vo_never: (pins.vo_never ?? []).filter(x => x !== phrase) })

/** The user edited a narration item: the new wording becomes a pin (every word of it is theirs now, so green), replacing pins that sat inside the old wording. */
export function editNarration(pins: ScriptPins, oldText: string, newText: string, clip: string): ScriptPins {
  if (same(oldText, newText)) return pins
  const kept = { ...pins, vo: (pins.vo ?? []).filter(p => !(inside(p.text, oldText) && (p.mode !== 'clip' || p.clip === clip))) }
  return addPin(kept, newText, clip)
}

export type Part = { t: string; kind?: 'must' | 'never' }
/** The text cut into parts, marking where a pinned phrase (green) or a never-say phrase (red, wins) occurs; matching ignores case. */
export function highlight(text: string, must: string[], never: string[]): Part[] {
  const kind: (undefined | 'must' | 'never')[] = new Array(text.length).fill(undefined), low = text.toLowerCase()
  const mark = (phrases: string[], k: 'must' | 'never') => { for (const p of phrases) { const q = p.trim().toLowerCase(); if (!q) continue; for (let i = low.indexOf(q); i >= 0; i = low.indexOf(q, i + 1)) for (let j = i; j < i + q.length; j++) kind[j] = k } }
  mark(must, 'must'); mark(never, 'never')
  const out: Part[] = []
  for (let i = 0; i < text.length; i++) { const last = out[out.length - 1]; if (last && last.kind === kind[i]) last.t += text[i]; else out.push({ t: text[i], kind: kind[i] }) }
  return out
}
