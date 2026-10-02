import { Fragment, useEffect, useRef, useState } from 'react'
import { api, type WordT } from '../api'
import { STATE_CLASS, STATE_NAME, baseLine, wordState } from '../marks'

export type Mode = 'translated' | 'original' | 'both'
const LANG: Record<string, string> = { en: 'English', fr: 'French', nl: 'Dutch', de: 'German', es: 'Spanish', it: 'Italian' }
export const isForeign = (lang: string, text: string, en: string | null) => lang !== 'en' && !!en && en.trim() !== text.trim()

// One recognised phrase. English is plain. A phrase in another language shows its English translation in blue by default (chip "FR → EN") and its original words in amber (chip "FR"):
// click the chip to flip between them; the mode switch above the transcript sets what everything shows first (translated, original, or both).
export type WordCtx = { folder: string; clip: string; si: number; words: WordT[]; onSaved: () => void; used?: Set<string> }

const tip = (w: WordT, state = '') => !w.e ? `${w.t0.toFixed(1)} s${state ? ' · ' + state : ''} · click to correct this word` : `Original: "${w.e.orig}"\nChanged by ${w.e.src === 'user' ? 'you' : 'Gemini'}${w.e.src === 'gemini' && w.e.why ? `: ${w.e.why}` : ''}${w.e.src === 'user' && w.e.gemini_text ? `\nGemini suggested "${w.e.gemini_text}"` : ''}\nclick to edit`

// The words of a phrase, one by one: a corrected word is highlighted (amber = Gemini, blue = you) and hovering shows the original and who changed it; clicking a word edits it. A correction replaces
// one recognised word and keeps its timing, so nothing that depends on timing moves.
function Words({ ctx }: { ctx: WordCtx }) {
  const [open, setOpen] = useState<number>()
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { if (open != null) input.current?.select() }, [open])
  const save = async (i: number, text: string | null) => { setOpen(undefined); await api.editWord(ctx.folder, ctx.clip, ctx.si, i, text); ctx.onSaved() }
  const lineUsed = !!ctx.used?.has(baseLine(ctx.clip, ctx.si))
  return <>{ctx.words.map((w, k) => { const i = w.i ?? k; const st = wordState(w, lineUsed); return (
    <Fragment key={i}>
      <span className="relative inline-block">
        <span title={tip(w, st === 'free' ? '' : STATE_NAME[st])} data-wclip={ctx.clip} data-wseg={ctx.si} data-wi={i} data-state={st} onClick={e => { e.stopPropagation(); if (window.getSelection()?.isCollapsed === false) return; setOpen(i) }}
          className={`cursor-text rounded px-0.5 ${STATE_CLASS[st]} ${w.e ? `underline decoration-dotted decoration-2 underline-offset-2 ${w.e.src === 'user' ? 'decoration-sky-500' : 'decoration-amber-500'}` : ''} ${w.w.trim() === '' ? 'line-through opacity-60' : ''}`}>{w.w.trim() === '' ? (w.e?.orig ?? '') : w.w}</span>
        {open === i && (
          <span className="absolute left-0 top-full z-30 mt-1 flex w-64 flex-col gap-1 rounded-lg border border-stone-300 bg-white p-2 text-xs shadow-lg dark:border-stone-700 dark:bg-stone-900" onClick={e => e.stopPropagation()}>
            <input ref={input} defaultValue={w.w} autoFocus onKeyDown={e => { if (e.key === 'Enter') void save(i, e.currentTarget.value); if (e.key === 'Escape') setOpen(undefined) }} className="rounded border border-stone-300 bg-transparent px-1.5 py-1 text-sm dark:border-stone-700" />
            <span className="text-stone-500">{w.e ? `original: “${w.e.orig}”` : 'empty removes the word'} · Enter saves, Esc cancels</span>
            <span className="flex flex-wrap gap-1">
              <button className="rounded bg-emerald-700 px-2 py-0.5 text-white" onClick={() => void save(i, input.current?.value ?? w.w)}>save</button>
              {w.e && <button className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-700" onClick={() => void save(i, w.e!.orig)}>use the original</button>}
              {w.e?.src === 'user' && w.e.gemini_text != null && <button className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-700" onClick={() => void save(i, null)}>use Gemini’s “{w.e.gemini_text || '∅'}”</button>}
              {w.e?.src === 'user' && w.e.gemini_text == null && <button className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-700" onClick={() => void save(i, null)}>forget my edit</button>}
              <button className="rounded border border-stone-300 px-2 py-0.5 dark:border-stone-700" onClick={() => setOpen(undefined)}>cancel</button>
            </span>
          </span>)}
      </span>{' '}
    </Fragment>) })}</>
}

export default function Phrase({ text, en, lang, mode, className = '', onText, word }: { text: string; en: string | null; lang: string; mode: Mode; className?: string; onText?: () => void; word?: WordCtx }) {
  const [flip, setFlip] = useState(false)
  if (!isForeign(lang, text, en)) return word ? <span className={className} onClick={onText}><Words ctx={word} /></span> : <span className={className} onClick={onText}>{text}</span>
  const L = lang.toUpperCase(), name = LANG[lang] ?? lang
  const chip = (translated: boolean) => (
    <button type="button" title={translated ? `Translated from ${name}: click to see the original` : `Original ${name}: click to see the translation`}
      onClick={e => { e.stopPropagation(); setFlip(f => !f) }}
      className={`mr-1 rounded-full border px-1.5 align-baseline text-[10px] font-medium leading-4 ${translated ? 'border-sky-400 text-sky-700 dark:text-sky-300' : 'border-amber-500 text-amber-700 dark:text-amber-300'}`}>
      {translated ? `${L} → EN` : L}
    </button>
  )
  const orig = <span className="text-amber-700 dark:text-amber-300" onClick={onText}>{word ? <Words ctx={word} /> : text}</span>
  const tr = <span className="text-sky-700 dark:text-sky-300" onClick={onText}>{en}</span>
  if (mode === 'both') return <span className={className}>{chip(false)}{orig} {chip(true)}{tr}</span>
  const showTranslated = (mode === 'translated') !== flip
  return <span className={className}>{chip(showTranslated)}{showTranslated ? tr : orig}</span>
}
