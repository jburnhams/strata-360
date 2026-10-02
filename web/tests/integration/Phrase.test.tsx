import { describe, expect, it } from 'vitest'
import Phrase from '../../src/components/Phrase'
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
