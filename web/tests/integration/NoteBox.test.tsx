import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import NoteBox from '../../src/components/NoteBox'
import { mockGet, mockPending, recordRequests, mockError } from '../utils/api'
import { makeNotes } from '../utils/factories'
import { act, screen, setup } from '../utils/render'

const props = { folder: '/f', title: 'Notes', placeholder: 'Write here' }
// Typing is debounced by 600 ms: fake timers, with user-event told to advance them.
const typing = () => setup(<NoteBox {...props} />, undefined)

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers() })

describe('NoteBox', () => {
  it('loads the folder note into the box', async () => {
    mockGet('/api/notes', makeNotes({ folder: 'sunny day' }))
    typing()
    expect(await screen.findByPlaceholderText('Write here')).toHaveValue('sunny day')
    expect(screen.getByText('saved')).toBeInTheDocument()
  })

  it('loads the note of one clip, and an empty box for a clip without one', async () => {
    mockGet('/api/notes', makeNotes({ folder: 'all', clips: { a: 'clip a' } }))
    const { rerender } = setup(<NoteBox {...props} clip="a" />)
    expect(await screen.findByPlaceholderText('Write here')).toHaveValue('clip a')
    rerender(<NoteBox {...props} clip="b" />)
    await vi.waitFor(() => expect(screen.getByPlaceholderText('Write here')).toHaveValue(''))
  })

  it('saves once, after typing stops, then says so', async () => {
    const seen = recordRequests('/api/notes')
    const { user } = typing()
    const box = await screen.findByPlaceholderText('Write here')
    await user.type(box, 'abc')
    expect(screen.getByText('saving…')).toBeInTheDocument()
    expect(seen.filter(r => r.method === 'POST')).toHaveLength(0)
    await act(() => vi.advanceTimersByTimeAsync(700))
    await vi.waitFor(() => expect(screen.getByText('saved')).toBeInTheDocument())
    expect(seen.filter(r => r.method === 'POST')).toMatchObject([{ body: { folder: '/f', text: 'abc' } }])
  })

  it('saves a clip note against that clip', async () => {
    const seen = recordRequests('/api/notes')
    const { user } = setup(<NoteBox {...props} clip="c1" />)
    await user.type(await screen.findByPlaceholderText('Write here'), 'x')
    await act(() => vi.advanceTimersByTimeAsync(700))
    await vi.waitFor(() => expect(seen.some(r => r.method === 'POST')).toBe(true))
    expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ clip: 'c1', text: 'x' })
  })

  it('does not save when unmounted before the delay is up', async () => {
    const seen = recordRequests('/api/notes')
    const { user, unmount } = typing()
    await user.type(await screen.findByPlaceholderText('Write here'), 'x')
    unmount()
    await vi.advanceTimersByTimeAsync(2000)
    expect(seen.filter(r => r.method === 'POST')).toHaveLength(0)
  })

  it('shows a skeleton, not an empty box, while the note loads', () => {
    mockPending('/api/notes')
    typing()
    expect(screen.queryByPlaceholderText('Write here')).not.toBeInTheDocument()
  })

  it('shows an empty box if notes fail to load', async () => {
    mockError('/api/notes', 500)
    typing()
    expect(await screen.findByPlaceholderText('Write here')).toHaveValue('')
  })
})
