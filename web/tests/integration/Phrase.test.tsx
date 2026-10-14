import { describe, expect, it, vi } from 'vitest'
import Phrase from '../../src/components/Phrase'
import { fireEvent } from '@testing-library/react'
import { mockPost, recordRequests } from '../utils/api'
import { screen, setup } from '../utils/render'

const A = 'CAM_20260222130830_0023_D'
const w = (i: number, t: string, extra: object = {}) => ({ i, w: t, t0: i, t1: i + 0.4, ...extra })
const ctx = (words: ReturnType<typeof w>[], used?: Set<string>) => ({ folder: '/data', clip: A, si: 27, words, onSaved: () => {}, used })

describe('Phrase word colours', () => {
  it('shows green for must use, red for never use, yellow for unmarked words the draft plays, and nothing for the rest', () => {
    setup(<Phrase text="a b c d" en={null} lang="en" mode="translated" word={ctx([w(0, 'a', { m: 'must' }), w(1, 'b', { m: 'never' }), w(2, 'c'), w(3, 'd')], new Set(['0023.27']))} />)
    expect(screen.getByText('a')).toHaveAttribute('data-state', 'must')
    expect(screen.getByText('b')).toHaveAttribute('data-state', 'never')
    expect(screen.getByText('c')).toHaveAttribute('data-state', 'used')
    expect(screen.getByText('a')).toHaveAttribute('title', expect.stringContaining('must use'))
  })

  it('leaves unmarked words plain when the draft does not play the line', () => {
    setup(<Phrase text="a b" en={null} lang="en" mode="translated" word={ctx([w(0, 'a'), w(1, 'b')], new Set(['0023.28']))} />)
    expect(screen.getByText('a')).toHaveAttribute('data-state', 'free')
  })

  it('addresses every word by clip, segment and word number, for the selection', () => {
    setup(<Phrase text="a b" en={null} lang="en" mode="translated" word={ctx([w(4, 'a'), w(5, 'b')])} />)
    const el = screen.getByText('b'); expect(el.dataset).toMatchObject({ wclip: A, wseg: '27', wi: '5' })
  })

  it('marks a correction with a dotted underline instead of a background, and still shows the mark', () => {
    setup(<Phrase text="x" en={null} lang="en" mode="translated" word={ctx([w(0, 'fixed', { m: 'must', e: { orig: 'fixt', src: 'user', user_text: 'fixed' } })])} />)
    const el = screen.getByText('fixed'); expect(el).toHaveAttribute('data-state', 'must'); expect(el.className).toContain('decoration-dotted'); expect(el.className).toContain('decoration-sky-500')
  })

  it('opens the word editor on a plain click', async () => {
    const { user } = setup(<Phrase text="a" en={null} lang="en" mode="translated" word={ctx([w(0, 'a')])} />)
    await user.click(screen.getByText('a'))
    expect(await screen.findByText(/Enter saves, Esc cancels/)).toBeInTheDocument()
  })
})


describe('Phrase in another language', () => {
  it('shows the English translation first, with a chip naming the language', () => {
    setup(<Phrase text="bonjour" en="hello" lang="fr" mode="translated" />)
    expect(screen.getByText('hello')).toBeInTheDocument(); expect(screen.queryByText('bonjour')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'FR → EN' })).toHaveAttribute('title', 'Translated from French: click to see the original')
  })

  it('flips between the translation and the original with the chip', async () => {
    const { user } = setup(<Phrase text="bonjour" en="hello" lang="fr" mode="translated" />)
    await user.click(screen.getByRole('button', { name: 'FR → EN' }))
    expect(screen.getByText('bonjour')).toBeInTheDocument(); expect(screen.queryByText('hello')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'FR' })); expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('starts with the original when the transcript is set to original, and flips to the translation', async () => {
    const { user } = setup(<Phrase text="bonjour" en="hello" lang="fr" mode="original" />)
    expect(screen.getByText('bonjour')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'FR' })); expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('shows both the original and the translation, each with its chip', () => {
    setup(<Phrase text="bonjour" en="hello" lang="fr" mode="both" />)
    expect(screen.getByText('bonjour')).toBeInTheDocument(); expect(screen.getByText('hello')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'FR' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'FR → EN' })).toBeInTheDocument()
  })

  it('uses the code of a language it has no name for', () => {
    setup(<Phrase text="hej" en="hi" lang="sv" mode="translated" />)
    expect(screen.getByRole('button', { name: 'SV → EN' })).toHaveAttribute('title', 'Translated from sv: click to see the original')
  })

  it('treats a translation that equals the text, or none, as plain text with no chip', () => {
    const { rerender } = setup(<Phrase text="ok" en=" ok " lang="nl" mode="translated" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument(); expect(screen.getByText('ok')).toBeInTheDocument()
    rerender(<Phrase text="ok" en={null} lang="nl" mode="translated" />); expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('flipping the chip does not count as a click on the phrase, but a click on the words does', async () => {
    const onText = vi.fn(); const { user } = setup(<Phrase text="bonjour" en="hello" lang="fr" mode="translated" onText={onText} />)
    await user.click(screen.getByRole('button', { name: 'FR → EN' })); expect(onText).not.toHaveBeenCalled()
    await user.click(screen.getByText('bonjour')); expect(onText).toHaveBeenCalledTimes(1)
  })

  it('lets the original words be corrected in a foreign phrase', async () => {
    const { user } = setup(<Phrase text="bonjour" en="hello" lang="fr" mode="original" word={ctx([w(0, 'bonjour')])} />)
    await user.click(screen.getByText('bonjour')); expect(await screen.findByText(/empty removes the word/)).toBeInTheDocument()
  })

  it('calls the handler when a plain English phrase is clicked', async () => {
    const onText = vi.fn(); const { user } = setup(<Phrase text="just english" en={null} lang="en" mode="both" onText={onText} />)
    await user.click(screen.getByText('just english')); expect(onText).toHaveBeenCalledTimes(1)
  })
})

describe('Phrase word corrections', () => {
  const open = async (word: ReturnType<typeof w>, onSaved = vi.fn()) => {
    const seen = recordRequests('/api/transcript/edit'); mockPost('/api/transcript/edit', { ok: true })
    const view = setup(<Phrase text="x" en={null} lang="en" mode="translated" word={{ ...ctx([word]), onSaved }} />)
    await view.user.click(screen.getByText(word.w)); await screen.findByText(/Enter saves, Esc cancels/)
    return { ...view, seen, onSaved }
  }

  it('saves the typed word with Enter, keeping its place, and tells the parent', async () => {
    const { user, seen, onSaved } = await open(w(3, 'helo'))
    const box = screen.getByRole('textbox'); await user.clear(box); await user.type(box, 'hello{Enter}')
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(seen).toMatchObject([{ method: 'POST', body: { folder: '/data', clip: A, seg: 27, word: 3, text: 'hello' } }])
    expect(screen.queryByText(/Enter saves/)).not.toBeInTheDocument()
  })

  it('saves with the save button', async () => {
    const { user, seen } = await open(w(0, 'helo')); const box = screen.getByRole('textbox'); await user.clear(box); await user.type(box, 'hullo')
    await user.click(screen.getByRole('button', { name: 'save' })); await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ word: 0, text: 'hullo' })
  })

  it('removes a word by saving it empty', async () => {
    const { user, seen } = await open(w(0, 'um')); await user.clear(screen.getByRole('textbox')); await user.click(screen.getByRole('button', { name: 'save' }))
    await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ text: '' })
  })

  it('closes with Escape or cancel without saving', async () => {
    const { user, seen, onSaved } = await open(w(0, 'helo'))
    await user.keyboard('{Escape}'); expect(screen.queryByText(/Enter saves/)).not.toBeInTheDocument()
    await user.click(screen.getByText('helo')); await user.click(await screen.findByRole('button', { name: 'cancel' }))
    expect(screen.queryByText(/Enter saves/)).not.toBeInTheDocument(); expect(seen).toEqual([]); expect(onSaved).not.toHaveBeenCalled()
  })

  it('offers to go back to the original of a word Gemini changed, and says who changed it', async () => {
    const word = w(0, 'fixed', { e: { orig: 'fixt', src: 'gemini', why: 'sounds like fixed' } })
    const { user, seen } = await open(word)
    expect(screen.getByText(/original: “fixt”/)).toBeInTheDocument(); expect(screen.queryByRole('button', { name: /Gemini’s/ })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'forget my edit' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'use the original' })); await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ text: 'fixt' })
  })

  it('offers Gemini’s suggestion back on a word the user changed, which clears the edit', async () => {
    const { user, seen } = await open(w(2, 'mine', { e: { orig: 'orig', src: 'user', gemini_text: 'theirs' } }))
    await user.click(screen.getByRole('button', { name: 'use Gemini’s “theirs”' })); await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', clip: A, seg: 27, word: 2, action: 'clear' })
  })

  it('shows an empty Gemini suggestion as a dash and offers to forget an edit Gemini never touched', async () => {
    const first = await open(w(0, 'mine', { e: { orig: 'orig', src: 'user', gemini_text: '' } })); expect(screen.getByRole('button', { name: 'use Gemini’s “∅”' })).toBeInTheDocument(); first.unmount()
    const { user, seen } = await open(w(1, 'mine', { e: { orig: 'orig', src: 'user' } }))
    await user.click(screen.getByRole('button', { name: 'forget my edit' })); await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ action: 'clear' })
  })

  it('describes the original and who changed a corrected word when hovering it', () => {
    setup(<Phrase text="x" en={null} lang="en" mode="translated" word={ctx([w(0, 'a', { e: { orig: 'b', src: 'gemini', why: 'context' } }), w(1, 'c', { e: { orig: 'd', src: 'user', gemini_text: 'e' } }), w(2, 'f')])} />)
    expect(screen.getByText('a')).toHaveAttribute('title', 'Original: "b"\nChanged by Gemini: context\nclick to edit')
    expect(screen.getByText('c')).toHaveAttribute('title', 'Original: "d"\nChanged by you\nGemini suggested "e"\nclick to edit')
    expect(screen.getByText('f')).toHaveAttribute('title', '2.0 s · click to correct this word')
  })

  it('shows a deleted word struck through with the word it was', () => {
    setup(<Phrase text="x" en={null} lang="en" mode="translated" word={ctx([w(0, ' ', { e: { orig: 'uh', src: 'user' } })])} />)
    expect(screen.getByText('uh').className).toContain('line-through')
  })

  it('does not open the editor while text is selected', async () => {
    setup(<Phrase text="x" en={null} lang="en" mode="translated" word={ctx([w(0, 'pick')])} />)
    const el = screen.getByText('pick'); const sel = window.getSelection()!; const r = document.createRange(); r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r)
    fireEvent.click(el); sel.removeAllRanges()
    expect(screen.queryByText(/Enter saves/)).not.toBeInTheDocument()
  })
})
