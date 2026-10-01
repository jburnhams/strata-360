import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { spansByClip, wordsInRange, type SelWord } from '../marks'

type State = 'must' | 'never' | 'none'

// Select words (drag across words, phrases and clips) and a small toolbar appears: green = MUST USE, red = NEVER USE, white = don't care (clears the marks). Keys G, R and W do the same while words are selected.
// The marks are saved per word (transcript_marks.json) and reach the script writer; they also keep the transcript's own corrections.
export default function WordMarker({ folder, onSaved, children }: { folder: string; onSaved: () => void; children: React.ReactNode }) {
  const root = useRef<HTMLDivElement>(null)
  const [sel, setSel] = useState<{ words: SelWord[]; x: number; y: number }>()
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string>()
  useEffect(() => {
    const on = () => {
      const s = window.getSelection(), r = s && s.rangeCount ? s.getRangeAt(0) : null
      if (!r || r.collapsed || !root.current || !root.current.contains(r.commonAncestorContainer)) { setSel(undefined); return }
      const words = wordsInRange(root.current, r); if (!words.length) { setSel(undefined); return }
      const b = typeof r.getBoundingClientRect === 'function' ? r.getBoundingClientRect() : { left: 0, width: 0, top: 0 }; setSel({ words, x: b.left + b.width / 2, y: b.top })
    }
    document.addEventListener('selectionchange', on); return () => document.removeEventListener('selectionchange', on)
  }, [])
  const mark = async (state: State) => {
    if (!sel || busy) return
    setBusy(true); setErr(undefined)
    try { for (const [clip, spans] of spansByClip(sel.words)) await api.markWords(folder, clip, spans, state); window.getSelection()?.removeAllRanges(); setSel(undefined); onSaved() } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  useEffect(() => {
    if (!sel) return
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.ctrlKey || e.metaKey || e.altKey || (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable))) return
      const k = e.key.toLowerCase(); if (k === 'g') void mark('must'); else if (k === 'r') void mark('never'); else if (k === 'w') void mark('none')
    }
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key)
  })
  const clips = sel ? new Set(sel.words.map(w => w.clip)).size : 0
  const btn = 'rounded px-2 py-1 text-xs font-medium disabled:opacity-50'
  return (
    <div ref={root}>
      {children}
      {(sel || err) && (
        <div role="toolbar" aria-label="Mark the selected words" className="fixed z-50 flex items-center gap-1 rounded-lg border border-stone-300 bg-white p-1 shadow-lg dark:border-stone-700 dark:bg-stone-900"
          style={{ left: Math.max((sel?.x ?? 120) - 130, 8), top: Math.max((sel?.y ?? 80) - 44, 8) }} onMouseDown={e => e.preventDefault()}>
          {sel && <span className="px-1 text-xs text-stone-500">{sel.words.length} word{sel.words.length === 1 ? '' : 's'}{clips > 1 ? ` in ${clips} clips` : ''}</span>}
          <button disabled={busy} className={`${btn} bg-emerald-200 text-emerald-900 dark:bg-emerald-500/40 dark:text-emerald-100`} title="the film must use these words (G)" onClick={() => void mark('must')}>Must use</button>
          <button disabled={busy} className={`${btn} bg-red-200 text-red-900 dark:bg-red-500/40 dark:text-red-100`} title="the film must never use these words, and their sound is never heard (R)" onClick={() => void mark('never')}>Never use</button>
          <button disabled={busy} className={`${btn} border border-stone-300 dark:border-stone-600`} title="no preference: clear the marks (W)" onClick={() => void mark('none')}>Clear</button>
          {err && <span className="px-1 text-xs text-red-600">{err}</span>}
        </div>)}
    </div>
  )
}
