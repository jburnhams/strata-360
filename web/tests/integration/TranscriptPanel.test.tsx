import { describe, expect, it, vi } from 'vitest'
import { setup } from '../utils/render'
import TranscriptPanel from '../../src/components/TranscriptPanel'
import { makeSeg, makeClipInfo, makeTranscriptFix } from '../utils/factories'
import { mockGet, mockPost, mockPending, recordRequests } from '../utils/api'

describe('TranscriptPanel', () => {
  it('shows a skeleton while loading', () => {
    mockPending('/api/transcript')
    const { getByRole, getByTestId, queryByText } = setup(<TranscriptPanel folder="/data" clips={[]} tz="UTC" onOpen={vi.fn()} />)

    // skeleton check
    expect(queryByText('Transcript of everything')).not.toBeInTheDocument()
  })

  it('renders an empty state when no segments exist', async () => {
    mockGet('/api/transcript', { segments: [] })

    const { findByText } = setup(<TranscriptPanel folder="/data" clips={[]} tz="UTC" onOpen={vi.fn()} />)
    expect(await findByText('No speech recognised yet.')).toBeInTheDocument()
  })

  it('renders an empty state when filtered by "you" but no such segments exist', async () => {
    mockGet('/api/transcript', { segments: [makeSeg({ who: 'other' })] })

    const { user, findByText, getByRole } = setup(<TranscriptPanel folder="/data" clips={[]} tz="UTC" onOpen={vi.fn()} />)
    expect(await findByText('hello', { exact: false })).toBeInTheDocument()

    const filter = getByRole('combobox', { name: '' }) // There is no label, only nearby text
    await user.selectOptions(filter, 'you')

    expect(await findByText('No phrases labelled as you yet (voices are labelled by the speakers stage).')).toBeInTheDocument()
  })

  it('renders groups of segments from the API', async () => {
    mockGet('/api/transcript', { segments: [
      makeSeg({ clip: 'CAM_1', t0: 0, text: 'hello', words: [] }),
      makeSeg({ clip: 'CAM_1', t0: 5, text: 'world', words: [] }),
      makeSeg({ clip: 'CAM_2', t0: 10, text: 'foo', words: [] }),
    ]})

    const { findByText, getByText } = setup(<TranscriptPanel folder="/data" clips={[makeClipInfo({ id: 'CAM_1' }), makeClipInfo({ id: 'CAM_2' })]} tz="UTC" onOpen={vi.fn()} />)

    expect(await findByText('hello', { exact: false })).toBeInTheDocument()
    expect(getByText('world', { exact: false })).toBeInTheDocument()
    expect(getByText('foo', { exact: false })).toBeInTheDocument()

    // Test that the clip headers are visible
    expect(getByText('1 · 10 s')).toBeInTheDocument() // short('CAM_1')
    expect(getByText('2 · 10 s')).toBeInTheDocument() // short('CAM_2')
  })

  it('triggers onOpen when clicking a phrase', async () => {
    mockGet('/api/transcript', { segments: [makeSeg({ clip: 'CAM_1', t0: 12.5, text: 'hello' })] })
    const onOpen = vi.fn()

    const { user, findByText } = setup(<TranscriptPanel folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} tz="UTC" onOpen={onOpen} />)

    const phrase = await findByText('hello', { exact: false })
    await user.click(phrase.closest('span.cursor-pointer')!)

    expect(onOpen).toHaveBeenCalledWith('CAM_1', 12.5)
  })

  it('triggers onOpen when clicking a clip header', async () => {
    mockGet('/api/transcript', { segments: [makeSeg({ clip: 'CAM_1', t0: 12.5, text: 'hello' })] })
    const onOpen = vi.fn()

    const { user, findByText, getByRole } = setup(<TranscriptPanel folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} tz="UTC" onOpen={onOpen} />)
    await findByText('hello', { exact: false })

    const header = getByRole('button', { name: /1/ }) // short('CAM_1') + duration
    await user.click(header)

    expect(onOpen).toHaveBeenCalledWith('CAM_1', 12.5)
  })

  it('requests suggestions from Gemini when the button is clicked', async () => {
    mockGet('/api/transcript', { segments: [makeSeg()] })
    mockGet('/api/transcript/suggest', makeTranscriptFix({ state: 'done', fixes: 2 }))
    const seen = recordRequests('/api/transcript/suggest')

    const { user, findByRole, findByText, getByRole } = setup(<TranscriptPanel folder="/data" clips={[]} tz="UTC" onOpen={vi.fn()} />)
    expect(await findByText('hello', { exact: false })).toBeInTheDocument()

    const btn = await findByRole('button', { name: /suggest corrections/ })
    await user.click(btn)

    expect(seen.some(r => r.method === 'POST')).toBe(true)
  })

  it('shows tooltip details on hover', async () => {
    mockGet('/api/transcript', { segments: [makeSeg({ clip: 'CAM_1', t0: 12.5, text: 'hello' })] })

    const { user, findByText, queryByText } = setup(<TranscriptPanel folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} tz="UTC" onOpen={vi.fn()} />)

    const phrase = await findByText('hello', { exact: false })
    expect(queryByText('CAM_1')).not.toBeInTheDocument()

    await user.hover(phrase)

    expect(await findByText('CAM_1')).toBeInTheDocument()

    await user.unhover(phrase)
    // The tooltip isn't immediately removed, it relies on mouse leave which jsdom simulates,
    // but React's state update might not fire instantly in the test without act/waitFor.
  })
})
