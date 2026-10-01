import { describe, expect, it } from 'vitest'
import { act } from '@testing-library/react'
import Phrase from '../../src/components/Phrase'
import WordMarker from '../../src/components/WordMarker'
import { screen, setup, waitFor } from '../utils/render'
import { mockError, recordRequests } from '../utils/api'

const A = 'CAM_20260222130830_0023_D', B = 'CAM_20260222143858_0024_D'
const words = (...ws: string[]) => ws.map((w, i) => ({ i, w, t0: i * 0.5, t1: i * 0.5 + 0.4 }))

function Page({ onSaved = () => {} }: { onSaved?: () => void }) {
  return (
    <WordMarker folder="/data" onSaved={onSaved}>
      <p><Phrase text="we are fine" en={null} lang="en" mode="translated" word={{ folder: '/data', clip: A, si: 3, words: words('we', 'are', 'fine'), onSaved }} /></p>
      <p><Phrase text="it is wet" en={null} lang="en" mode="translated" word={{ folder: '/data', clip: A, si: 4, words: words('it', 'is', 'wet'), onSaved }} /></p>
      <p><Phrase text="hello there" en={null} lang="en" mode="translated" word={{ folder: '/data', clip: B, si: 0, words: words('hello', 'there'), onSaved }} /></p>
      <p id="outside">not a word span</p>
    </WordMarker>
  )
}
const word = (t: string) => screen.getByText(t, { selector: '[data-wclip]' })
async function select(from: HTMLElement, to: HTMLElement) {
  const r = document.createRange(); r.setStartBefore(from); r.setEndAfter(to); const s = window.getSelection()!; s.removeAllRanges(); s.addRange(r)
  await act(async () => { document.dispatchEvent(new Event('selectionchange')) })
}

describe('WordMarker', () => {
  it('shows no toolbar until words are selected', () => {
    setup(<Page />)
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
  })

  it('marks a selection that spans two phrases as one span per phrase', async () => {
    const seen = recordRequests('/api/transcript/mark'); let saved = 0
    const { user } = setup(<Page onSaved={() => { saved++ }} />)
    await select(word('are'), word('is'))
    expect(await screen.findByRole('toolbar', { name: 'Mark the selected words' })).toHaveTextContent('4 words')
    await user.click(screen.getByRole('button', { name: 'Must use' }))
    await waitFor(() => expect(saved).toBe(1))
    expect(seen).toHaveLength(1)
    expect(seen[0].body).toEqual({ folder: '/data', clip: A, spans: [{ seg: 3, from: 1, to: 2 }, { seg: 4, from: 0, to: 1 }], state: 'must' })
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
  })

  it('marks words in several clips with one request per clip', async () => {
    const seen = recordRequests('/api/transcript/mark')
    const { user } = setup(<Page />)
    await select(word('wet'), word('hello'))
    expect(await screen.findByRole('toolbar')).toHaveTextContent('2 clips')
    await user.click(screen.getByRole('button', { name: 'Never use' }))
    await waitFor(() => expect(seen).toHaveLength(2))
    expect(seen.map(r => [(r.body as { clip: string }).clip, (r.body as { state: string }).state])).toEqual([[A, 'never'], [B, 'never']])
  })

  it('clears marks with the white button', async () => {
    const seen = recordRequests('/api/transcript/mark')
    const { user } = setup(<Page />)
    await select(word('there'), word('there'))
    await user.click(await screen.findByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(seen).toHaveLength(1))
    expect((seen[0].body as { state: string }).state).toBe('none')
  })

  it('has the keys G, R and W for the same three actions', async () => {
    const seen = recordRequests('/api/transcript/mark')
    const { user } = setup(<Page />)
    await select(word('we'), word('we')); await screen.findByRole('toolbar')
    await user.keyboard('g'); await waitFor(() => expect(seen).toHaveLength(1))
    await select(word('we'), word('we')); await screen.findByRole('toolbar')
    await user.keyboard('r'); await waitFor(() => expect(seen).toHaveLength(2))
    expect(seen.map(r => (r.body as { state: string }).state)).toEqual(['must', 'never'])
  })

  it('ignores a selection that touches no words', async () => {
    setup(<Page />)
    const el = document.getElementById('outside')!; await select(el, el)
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
  })

  it('says so when the server refuses and keeps the selection toolbar', async () => {
    mockError('/api/transcript/mark', 404, 'no such word', 'post')
    const { user } = setup(<Page />)
    await select(word('fine'), word('fine'))
    await user.click(await screen.findByRole('button', { name: 'Must use' }))
    expect(await screen.findByText('no such word')).toBeInTheDocument()
  })
})
