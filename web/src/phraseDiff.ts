// Turns a whole retyped phrase into the word-by-word corrections the server stores. A correction replaces one recognised word and keeps its timing, so the retyped text is lined up with the shown words:
// words that are still there are left alone; where the same number of words changed they are replaced one for one; where the count differs, the new words go on the first word of the changed stretch
// and the rest of it is emptied (a hidden word); words added with nothing to replace are tacked onto the word before.
export interface DiffWord { i: number; w: string }
export interface WordChange { i: number; text: string }

const toks = (s: string) => s.split(/\s+/).filter(Boolean)

export function diffPhrase(words: DiffWord[], text: string): WordChange[] {
  const subs: { owner: number; t: string }[] = []        // the shown words broken into tokens (a corrected word may hold several), each remembering its word
  for (const w of words) for (const t of toks(w.w)) subs.push({ owner: w.i, t })
  const nw = toks(text), n = subs.length, m = nw.length
  const L: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let a = n - 1; a >= 0; a--) for (let b = m - 1; b >= 0; b--) L[a][b] = subs[a].t === nw[b] ? L[a + 1][b + 1] + 1 : Math.max(L[a + 1][b], L[a][b + 1])
  const put: string[][] = subs.map(() => []); let lead: string[] = []        // the new tokens each old token becomes; `lead`: words typed before the first old token
  const gap = (a0: number, a1: number, b0: number, b1: number) => {
    const run = nw.slice(b0, b1)
    if (a1 > a0) { if (a1 - a0 === run.length) run.forEach((t, k) => put[a0 + k].push(t)); else run.forEach(t => put[a0].push(t)) }
    else if (run.length) { if (a0 > 0) put[a0 - 1].push(...run); else lead = lead.concat(run) }
  }
  let a = 0, b = 0, ga = 0, gb = 0
  while (a < n && b < m) {
    if (subs[a].t === nw[b]) { gap(ga, a, gb, b); put[a].push(nw[b]); a++; b++; ga = a; gb = b }
    else if (L[a + 1][b] >= L[a][b + 1]) a++
    else b++
  }
  gap(ga, n, gb, m)
  const first = words.find(w => toks(w.w).length)       // words typed before everything else go in front of the first word
  const out: WordChange[] = []
  for (const w of words) {
    const mine = subs.flatMap((s, k) => s.owner === w.i ? put[k] : [])
    const text2 = [...(first && first.i === w.i ? lead : []), ...mine].join(' ')
    if (text2 !== toks(w.w).join(' ')) out.push({ i: w.i, text: text2 })
  }
  if (!first && lead.length && words.length) out.push({ i: words[0].i, text: lead.join(' ') })
  return out
}
