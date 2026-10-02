import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import MusicPanel from '../../src/components/MusicPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeMusicState, makeLyrics } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('MusicPanel', () => {
  it('offers an upload and no player when there is no track', async () => {
    setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)
    expect(await screen.findByText('Music')).toBeInTheDocument()
    expect(await screen.findByText('Upload a track')).toBeInTheDocument()
    expect(screen.getByText(/Without a track the plan uses a steady 120 bpm/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Music track')).not.toBeInTheDocument()
    expect(screen.queryByText('change')).not.toBeInTheDocument()
  })

  it('shows the file name, a player, the waveform, the spectrogram and the bar lines for a track', async () => {
    mockGet('/api/music', makeMusicState({ file: 'music/track.mp3', name: 'My song.mp3', waveform: [0.1, 0.8, 0.4, 1], spectrogram: true,
      analysis: { bpm: 120, offset_s: 1, bar_beats: 4, duration_s: 10, usable_beats: 16, sections: [[0, 16, 0.5]], confidence: 0.9 } }))
    const { container } = setup(<MusicPanel folder="/data" />)
    expect(await screen.findByText('My song.mp3')).toBeInTheDocument()
    expect(screen.queryByText('Upload a track')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Music track')).toHaveAttribute('src', expect.stringContaining('/api/music/audio?'))
    expect(screen.getByRole('img', { name: /Waveform/ })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Spectrogram/ })).toHaveAttribute('src', expect.stringContaining('/api/music/spectrogram?'))
    expect(container.querySelectorAll('.pointer-events-none > div:not([data-testid])').length).toBe(5)       // bar lines at 1, 3, 5, 7, 9 s
    expect(screen.getByTestId('playhead')).toHaveStyle({ left: '0%' })
  })

  it('shades the sung stretches on the waveform when the lyrics are known, and shows nothing when they are not', async () => {
    mockGet('/api/music', makeMusicState({ file: 'music/track.mp3', name: 'My song.mp3', waveform: [0.1, 0.8], spectrogram: true,
      analysis: { bpm: 120, offset_s: 1, bar_beats: 4, duration_s: 10, usable_beats: 16, sections: [[0, 16, 0.5]], confidence: 0.9 } }))
    mockGet('/api/lyrics', makeLyrics({ exists: true, phrases: 2, sung_s: 5, duration_s: 10, vocal_spans: [[2, 4], [6, 9]] }))
    setup(<MusicPanel folder="/data" />)
    const bands = await screen.findAllByTestId('sung'); expect(bands).toHaveLength(2)
    expect(bands[0]).toHaveStyle({ left: '20%', width: '20%' }); expect(bands[1]).toHaveStyle({ left: '60%', width: '30%' }); expect(screen.getByText(/sung \(from the lyrics\)/)).toBeInTheDocument()
  })

  it('says so when the track cannot be read', async () => {
    mockGet('/api/music', makeMusicState({ file: 'music/track.mp3', name: 'x.mp3', analysis: null }))
    setup(<MusicPanel folder="/data" />)
    expect(await screen.findByText(/could not be read/)).toBeInTheDocument()
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
    expect(screen.getByText('change')).toBeInTheDocument()
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
    await screen.findByText('Upload a track')

    // change the get mock to simulate what happens when it polls after the post
    mockGet('/api/music', makeMusicState({ file: 'new.mp3', analysis: { bpm: 110, offset_s: 0, duration_s: 60, usable_beats: 100, sections: [[0, 100, 0.5]], confidence: 0.9 } }))

    const input = screen.getByLabelText(/Upload a track|change/)
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
    await screen.findByText('change')

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
    await screen.findByText('Upload a track')

    const input = screen.getByLabelText(/Upload a track|change/)
    const file = new File(['hello'], 'bad.mp3', { type: 'audio/mpeg' })
    await user.upload(input, file)

    expect(await screen.findByText('Invalid audio file')).toBeInTheDocument()
  })

  it('shows a warning message if upload completes with a warning', async () => {
    mockGet('/api/music', makeMusicState({ file: null }))
    mockPost('/api/music', { file: 'track.mp3', analysis: null, warning: 'This track is very short.' })
    mockGet('/api/music', makeMusicState({ file: 'track.mp3', analysis: null }))

    const { user } = setup(<MusicPanel folder="/data" onChanged={vi.fn()} />)
    await screen.findByLabelText(/Upload a track|change/)

    const input = screen.getByLabelText(/Upload a track|change/)
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
