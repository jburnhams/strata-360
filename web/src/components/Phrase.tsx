import { useState } from 'react'

export type Mode = 'translated' | 'original' | 'both'
const LANG: Record<string, string> = { en: 'English', fr: 'French', nl: 'Dutch', de: 'German', es: 'Spanish', it: 'Italian' }
export const isForeign = (lang: string, text: string, en: string | null) => lang !== 'en' && !!en && en.trim() !== text.trim()

// One recognised phrase. English is plain. A phrase in another language shows its English translation in blue by default (chip "FR → EN") and its original words in amber (chip "FR"):
// click the chip to flip between them; the mode switch above the transcript sets what everything shows first (translated, original, or both).
export default function Phrase({ text, en, lang, mode, className = '', onText }: { text: string; en: string | null; lang: string; mode: Mode; className?: string; onText?: () => void }) {
  const [flip, setFlip] = useState(false)
  if (!isForeign(lang, text, en)) return <span className={className} onClick={onText}>{text}</span>
  const L = lang.toUpperCase(), name = LANG[lang] ?? lang
  const chip = (translated: boolean) => (
    <button type="button" title={translated ? `Translated from ${name}: click to see the original` : `Original ${name}: click to see the translation`}
      onClick={e => { e.stopPropagation(); setFlip(f => !f) }}
      className={`mr-1 rounded-full border px-1.5 align-baseline text-[10px] font-medium leading-4 ${translated ? 'border-sky-400 text-sky-700 dark:text-sky-300' : 'border-amber-500 text-amber-700 dark:text-amber-300'}`}>
      {translated ? `${L} → EN` : L}
    </button>
  )
  const orig = <span className="text-amber-700 dark:text-amber-300" onClick={onText}>{text}</span>
  const tr = <span className="text-sky-700 dark:text-sky-300" onClick={onText}>{en}</span>
  if (mode === 'both') return <span className={className}>{chip(false)}{orig} {chip(true)}{tr}</span>
  const showTranslated = (mode === 'translated') !== flip
  return <span className={className}>{chip(showTranslated)}{showTranslated ? tr : orig}</span>
}
