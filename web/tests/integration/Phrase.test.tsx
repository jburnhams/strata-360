import { describe, expect, it, vi } from 'vitest'
import { setup } from '../utils/render'
import Phrase from '../../src/components/Phrase'
import { makeWordT } from '../utils/factories'
import { recordRequests, mockError, mockNetworkError } from '../utils/api'

describe('Phrase', () => {
  it('renders a plain English phrase', () => {
    const { getByText, queryByRole } = setup(<Phrase text="hello world" en="hello world" lang="en" mode="translated" />)
    expect(getByText('hello world')).toBeInTheDocument()
    expect(queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders a foreign phrase translated by default, and flips to original when clicked', async () => {
    const { user, getByText, getByRole, queryByText } = setup(<Phrase text="bonjour le monde" en="hello world" lang="fr" mode="translated" />)
    expect(getByText('hello world')).toBeInTheDocument()
    expect(queryByText('bonjour le monde')).not.toBeInTheDocument()

    const chip = getByRole('button', { name: 'FR → EN' })
    await user.click(chip)

    expect(getByText('bonjour le monde')).toBeInTheDocument()
    expect(queryByText('hello world')).not.toBeInTheDocument()
    const origChip = getByRole('button', { name: 'FR' })
    expect(origChip).toBeInTheDocument()
  })

  it('shows both modes side by side when mode is both', () => {
    const { getByText, getByRole } = setup(<Phrase text="bonjour" en="hello" lang="fr" mode="both" />)
    expect(getByText('bonjour')).toBeInTheDocument()
    expect(getByText('hello')).toBeInTheDocument()
    expect(getByRole('button', { name: 'FR' })).toBeInTheDocument()
    expect(getByRole('button', { name: 'FR → EN' })).toBeInTheDocument()
  })

  it('renders words for editing and allows saving an edit', async () => {
    const onSaved = vi.fn()
    const word = { folder: '/data', clip: 'C1', si: 42, words: [makeWordT({ w: 'test', i: 0 })], onSaved }
    const seen = recordRequests('/api/transcript/edit')

    const { user, getByText, getByRole, getByDisplayValue } = setup(<Phrase text="test" en="test" lang="en" mode="translated" word={word} />)

    const wordSpan = getByText('test')
    await user.click(wordSpan)

    const input = getByDisplayValue('test')
    await user.clear(input)
    await user.type(input, 'toast{enter}')

    expect(seen).toHaveLength(1)
    expect(seen[0].method).toBe('POST')
    expect(seen[0].body).toEqual({ folder: '/data', clip: 'C1', seg: 42, word: 0, text: 'toast' })
    expect(onSaved).toHaveBeenCalled()
  })

  it('allows clicking "save" button instead of enter', async () => {
    const onSaved = vi.fn()
    const word = { folder: '/data', clip: 'C1', si: 42, words: [makeWordT({ w: 'test', i: 0 })], onSaved }
    const seen = recordRequests('/api/transcript/edit')

    const { user, getByText, getByRole, getByDisplayValue } = setup(<Phrase text="test" en="test" lang="en" mode="translated" word={word} />)

    await user.click(getByText('test'))
    const input = getByDisplayValue('test')
    await user.clear(input)
    await user.type(input, 'toast')
    await user.click(getByRole('button', { name: 'save' }))

    expect(seen).toHaveLength(1)
    expect(seen[0].body).toEqual({ folder: '/data', clip: 'C1', seg: 42, word: 0, text: 'toast' })
    expect(onSaved).toHaveBeenCalled()
  })

  it('cancels edit on escape', async () => {
    const onSaved = vi.fn()
    const word = { folder: '/data', clip: 'C1', si: 42, words: [makeWordT({ w: 'test', i: 0 })], onSaved }

    const { user, getByText, getByDisplayValue, queryByDisplayValue } = setup(<Phrase text="test" en="test" lang="en" mode="translated" word={word} />)

    await user.click(getByText('test'))
    const input = getByDisplayValue('test')
    await user.type(input, '{escape}')

    expect(queryByDisplayValue('test')).not.toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('cancels edit on cancel button click', async () => {
    const onSaved = vi.fn()
    const word = { folder: '/data', clip: 'C1', si: 42, words: [makeWordT({ w: 'test', i: 0 })], onSaved }

    const { user, getByText, getByRole, queryByDisplayValue } = setup(<Phrase text="test" en="test" lang="en" mode="translated" word={word} />)

    await user.click(getByText('test'))
    await user.click(getByRole('button', { name: 'cancel' }))

    expect(queryByDisplayValue('test')).not.toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('handles words edited by user', async () => {
    const onSaved = vi.fn()
    const editedWord = makeWordT({ w: 'custom', i: 0, e: { orig: 'test', src: 'user', gemini_text: 'suggested' } })
    const word = { folder: '/data', clip: 'C1', si: 42, words: [editedWord], onSaved }
    const seen = recordRequests('/api/transcript/edit')

    const { user, getByText, getByRole } = setup(<Phrase text="custom" en="custom" lang="en" mode="translated" word={word} />)

    await user.click(getByText('custom'))
    expect(getByText('original: “test”', { exact: false })).toBeInTheDocument()

    await user.click(getByRole('button', { name: 'use the original' }))
    expect(seen).toHaveLength(1)
    expect(seen[0].body).toEqual({ folder: '/data', clip: 'C1', seg: 42, word: 0, text: 'test' })
  })

  it('handles using gemini suggestion', async () => {
    const onSaved = vi.fn()
    const editedWord = makeWordT({ w: 'custom', i: 0, e: { orig: 'test', src: 'user', gemini_text: 'suggested' } })
    const word = { folder: '/data', clip: 'C1', si: 42, words: [editedWord], onSaved }
    const seen = recordRequests('/api/transcript/edit')

    const { user, getByText, getByRole } = setup(<Phrase text="custom" en="custom" lang="en" mode="translated" word={word} />)

    await user.click(getByText('custom'))
    await user.click(getByRole('button', { name: 'use Gemini’s “suggested”' }))

    expect(seen).toHaveLength(1)
    expect(seen[0].body).toEqual({ folder: '/data', clip: 'C1', seg: 42, word: 0, action: 'clear' })
  })

  it('handles forgetting user edit when there is no gemini suggestion', async () => {
    const onSaved = vi.fn()
    const editedWord = makeWordT({ w: 'custom', i: 0, e: { orig: 'test', src: 'user', gemini_text: null } })
    const word = { folder: '/data', clip: 'C1', si: 42, words: [editedWord], onSaved }
    const seen = recordRequests('/api/transcript/edit')

    const { user, getByText, getByRole } = setup(<Phrase text="custom" en="custom" lang="en" mode="translated" word={word} />)

    await user.click(getByText('custom'))
    await user.click(getByRole('button', { name: 'forget my edit' }))

    expect(seen).toHaveLength(1)
    expect(seen[0].body).toEqual({ folder: '/data', clip: 'C1', seg: 42, word: 0, action: 'clear' })
  })

  it('renders an empty word with a line-through original', async () => {
    const editedWord = makeWordT({ w: ' ', i: 0, e: { orig: 'test', src: 'user' } })
    const word = { folder: '/data', clip: 'C1', si: 42, words: [editedWord], onSaved: vi.fn() }

    const { getByText } = setup(<Phrase text=" " en=" " lang="en" mode="translated" word={word} />)
    expect(getByText('test')).toHaveClass('line-through')
  })
})
