import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import MusicPanel from '../../src/components/MusicPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeMusicState } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('MusicPanel', () => {
  it('renders a skeleton or empty state while loading/no music', async () => {
    const { user } = setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)
    expect(await screen.findByText('Music')).toBeInTheDocument()
    expect(screen.getByText('Add a track')).toBeInTheDocument()
    expect(screen.getByText(/Without a track the plan uses a steady 120 bpm/)).toBeInTheDocument()
  })

  it('renders analysis details when a music track is present', async () => {
    mockGet('/api/music', makeMusicState({
      file: 'track.mp3',
      analysis: {
        bpm: 130,
        offset_s: 1.5,
        duration_s: 120,
        usable_beats: 200,
        sections: [[0, 50, 0.2], [50, 100, 0.8], [100, 200, 0.5]],
        confidence: 0.8
      }
    }))
    setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)

    expect(await screen.findByText(/130 bpm/)).toBeInTheDocument()
    expect(screen.getByText(/first bar at 1.5 s/)).toBeInTheDocument()
    expect(screen.getByText(/120 s long/)).toBeInTheDocument()
    expect(screen.getByText('Replace track')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'remove' })).toBeInTheDocument()
  })

  it('uploads a new music track and triggers onChanged', async () => {
    mockGet('/api/music', makeMusicState({ file: null, analysis: null }))
    // pick() in MusicPanel waits on api.uploadMusic, which calls POST /api/music.
    // And it doesn't return the MusicState inside the component. Actually, `MusicPanel` poll handles getting the state.
    // wait, we mock the POST correctly and then we need to mock the GET to simulate poll firing.
    mockPost('/api/music', makeMusicState({ file: 'new.mp3', analysis: { bpm: 110, offset_s: 0, duration_s: 60, usable_beats: 100, sections: [[0, 100, 0.5]], confidence: 0.9 } }))
    const seen = recordRequests('/api/music')
    const onChanged = vi.fn()

    const { user } = setup(<MusicPanel folder="/data" onChanged={onChanged} />)
    await screen.findByText('Add a track')

    // change the get mock to simulate what happens when it polls after the post
    mockGet('/api/music', makeMusicState({ file: 'new.mp3', analysis: { bpm: 110, offset_s: 0, duration_s: 60, usable_beats: 100, sections: [[0, 100, 0.5]], confidence: 0.9 } }))

    const input = screen.getByLabelText(/Add a track|Replace track/)
    const file = new File(['hello'], 'new.mp3', { type: 'audio/mpeg' })
    await user.upload(input, file)

    // Wait for the UI to update
    expect(await screen.findByText(/110 bpm/)).toBeInTheDocument()

    const postReq = seen.find(req => req.method === 'POST')
    expect(postReq).toBeDefined()
    expect(onChanged).toHaveBeenCalled()
  })

  it('removes a music track and triggers onChanged', async () => {
    mockGet('/api/music', makeMusicState({ file: 'track.mp3', analysis: { bpm: 120, offset_s: 0, duration_s: 60, usable_beats: 100, sections: [], confidence: 1 } }))
    const seen = recordRequests('/api/music')
    const onChanged = vi.fn()

    const { user } = setup(<MusicPanel folder="/data" onChanged={onChanged} />)
    await screen.findByText('Replace track')

    mockGet('/api/music', makeMusicState({ file: null, analysis: null })) // so next poll gets empty state
    await user.click(screen.getByRole('button', { name: 'remove' }))

    // We expect it to delete, and then poll again
    expect(seen.find(req => req.method === 'DELETE')).toBeDefined()
    expect(onChanged).toHaveBeenCalled()
  })

  it('shows an error message if upload fails', async () => {
    mockGet('/api/music', makeMusicState({ file: null }))
    mockError('/api/music', 500, 'Invalid audio file', 'post')

    const { user } = setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)
    await screen.findByText('Add a track')

    const input = screen.getByLabelText(/Add a track|Replace track/)
    const file = new File(['hello'], 'bad.mp3', { type: 'audio/mpeg' })
    await user.upload(input, file)

    expect(await screen.findByText('Invalid audio file')).toBeInTheDocument()
  })

  it('shows a warning message if upload completes with a warning', async () => {
    mockGet('/api/music', makeMusicState({ file: null }))
    mockPost('/api/music', { file: 'track.mp3', analysis: null, warning: 'This track is very short.' })
    mockGet('/api/music', makeMusicState({ file: 'track.mp3', analysis: null }))

    const { user } = setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)
    await screen.findByText('Add a track')

    const input = screen.getByLabelText(/Add a track|Replace track/)
    const file = new File(['hello'], 'short.mp3', { type: 'audio/mpeg' })
    await user.upload(input, file)

    expect(await screen.findByText('This track is very short.')).toBeInTheDocument()
  })

  it('shows uncertainty warning when confidence is low', async () => {
    mockGet('/api/music', makeMusicState({
      file: 'track.mp3',
      analysis: {
        bpm: 130,
        offset_s: 1.5,
        duration_s: 120,
        usable_beats: 200,
        sections: [],
        confidence: 0.2 // < 0.4
      }
    }))
    setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)

    expect(await screen.findByText(/the beat is uncertain/)).toBeInTheDocument()
  })

  it('has no accessibility violations once loaded', async () => {
    mockGet('/api/music', makeMusicState({ file: 'track.mp3', analysis: { bpm: 120, offset_s: 0, duration_s: 60, usable_beats: 100, sections: [[0, 50, 0.5]], confidence: 1 } }))
    const { container } = setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)
    await screen.findByText(/120 bpm/)
    expect(await axe(container)).toHaveNoViolations()
  })
})
