import type { WordMark, WordT } from './api'

// One colour language for the words of a transcript (and, later, of the script): green = MUST USE, red = NEVER USE, white = don't care, yellow = not marked but the current draft plays it.
// Yellow is not stored: it is worked out from the draft's lines. A transcript line is `<clip number>.<segment>` (the server splits it in pieces when the marks inside it differ; any piece counts for the whole line here).
export const clipLabel = (clip: string) => clip.match(/_(\d{4})_[A-Z]$/)?.[1] ?? clip.slice(-6)
export const baseLine = (clip: string, si: number) => `${clipLabel(clip)}.${String(si).padStart(2, '0')}`
export const baseOf = (lineId: string) => lineId.split('.').slice(0, 2).join('.')
export const usedSet = (lines: string[] | undefined) => new Set((lines ?? []).map(baseOf))

export type WordState = WordMark | 'used' | 'free'
export const wordState = (w: Pick<WordT, 'm'>, used: boolean): WordState => w.m ?? (used ? 'used' : 'free')
export const STATE_CLASS: Record<WordState, string> = {
  must: 'bg-emerald-200 dark:bg-emerald-500/40',
  never: 'bg-red-200 dark:bg-red-500/40',
  used: 'bg-yellow-200 dark:bg-yellow-500/30',
  free: 'hover:bg-stone-200 dark:hover:bg-stone-700',
}
export const STATE_NAME: Record<WordState, string> = { must: 'must use', never: 'never use', used: 'used by the draft', free: 'not used' }

export type SelWord = { clip: string; si: number; i: number }
export type Span = { seg: number; from: number; to: number }

/** The words (marked up with data-wclip / data-wseg / data-wi) that a text selection touches, in document order. */
export function wordsInRange(root: HTMLElement, range: Range): SelWord[] {
  const out: SelWord[] = []
  root.querySelectorAll<HTMLElement>('[data-wclip]').forEach(el => {
    if (range.intersectsNode(el)) out.push({ clip: el.dataset.wclip!, si: Number(el.dataset.wseg), i: Number(el.dataset.wi) })
  })
  return out
}

/** The selected words as one span per segment, per clip: a selection is contiguous, so the first and last word of a segment cover it. */
export function spansByClip(words: SelWord[]): Map<string, Span[]> {
  const seg = new Map<string, Map<number, [number, number]>>()
  for (const w of words) {
    const m = seg.get(w.clip) ?? new Map<number, [number, number]>(); seg.set(w.clip, m)
    const r = m.get(w.si); m.set(w.si, r ? [Math.min(r[0], w.i), Math.max(r[1], w.i)] : [w.i, w.i])
  }
  return new Map([...seg].map(([clip, m]) => [clip, [...m].sort((a, b) => a[0] - b[0]).map(([s, [from, to]]) => ({ seg: s, from, to }))]))
}
