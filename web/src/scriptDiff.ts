import type { ScriptItem } from './api'

// What changed between two drafts: an item counts as unchanged when its kind, clip and content (the narration's words, the lines it plays, the seconds of b-roll) are the same.
export const itemKey = (it: ScriptItem) => it.type === 'vo' ? `vo|${it.clip}|${it.text ?? ''}` : it.type === 'clip' ? `clip|${it.clip}|${it.from}|${it.to}` : `broll|${it.clip}|${Math.round(it.seconds ?? 0)}`

/** `added`: positions in `cur` with no match in `prev` (matched one for one); `removed`: the items of `prev` with no match in `cur`. */
export function diffDrafts(prev: ScriptItem[] | undefined, cur: ScriptItem[]): { added: Set<number>; removed: ScriptItem[] } {
  if (!prev) return { added: new Set(), removed: [] }
  const left = new Map<string, number>(); prev.forEach(it => left.set(itemKey(it), (left.get(itemKey(it)) ?? 0) + 1))
  const added = new Set<number>()
  cur.forEach((it, i) => { const k = itemKey(it), n = left.get(k) ?? 0; if (n > 0) left.set(k, n - 1); else added.add(i) })
  const removed: ScriptItem[] = []; const gone = new Map(left)
  prev.forEach(it => { const k = itemKey(it), n = gone.get(k) ?? 0; if (n > 0) { gone.set(k, n - 1); removed.push(it) } })
  return { added, removed }
}
