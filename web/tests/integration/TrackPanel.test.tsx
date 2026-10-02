import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import TrackPanel from '../../src/components/TrackPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeTrackOverview } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('TrackPanel', () => {
  it('renders a skeleton while loading', () => {
    mockPending('/api/track')
    setup(<TrackPanel folder="/data" />)
    expect(screen.getByText('Race track')).toBeInTheDocument()
    expect(screen.queryByText('Choose a file')).not.toBeInTheDocument()
  })

  it('renders the drag and drop upload view when no track is present', async () => {
    mockGet('/api/track', makeTrackOverview({ present: false }))
    setup(<TrackPanel folder="/data" />)
    expect(await screen.findByText('No race track yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose a file' })).toBeInTheDocument()
  })

  it('renders track metrics and SVG map when track is present', async () => {
    mockGet('/api/track', makeTrackOverview({
      present: true,
      file: 'my_track.fit',
      distance_km: 42.2,
      duration_h: 3.5,
      moving_h: 3.4,
      avg_pace_min_km: 5.5,
      bbox: [40, 10, 41, 11],
      line: [[40, 10], [41, 11]]
    }))

    setup(<TrackPanel folder="/data" />)

    expect(await screen.findByText(/my_track\.fit/)).toBeInTheDocument()
    expect(screen.getByText('Distance')).toBeInTheDocument()
    expect(screen.getByText('42.2')).toBeInTheDocument()
    expect(screen.getByText('5:30')).toBeInTheDocument() // 5.5 => 5:30 min/km
    expect(screen.getByRole('img', { name: 'Track overview' })).toBeInTheDocument()
  })

  it('uploads a file and refreshes', async () => {
    mockGet('/api/track', makeTrackOverview({ present: false }))
    mockPost('/api/track', makeTrackOverview({ present: true, file: 'new.fit', distance_km: 5 }))
    const seen = recordRequests('/api/track')

    const { user } = setup(<TrackPanel folder="/data" />)
    await screen.findByText('No race track yet.')

    // Simulate file input
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['hello'], 'new.fit', { type: 'application/octet-stream' })
    await user.upload(input, file)

    // Wait for the UI to update to the present state
    expect(await screen.findByText(/new\.fit/)).toBeInTheDocument()
    expect(seen.find(req => req.method === 'POST')).toMatchObject({ method: 'POST' })
  })

  it('shows error if GET /api/track fails', async () => {
    mockError('/api/track', 500, 'server died')
    setup(<TrackPanel folder="/data" />)
    expect(await screen.findByText('server died')).toBeInTheDocument()
  })

  it('shows error if uploading fails', async () => {
    mockGet('/api/track', makeTrackOverview({ present: false }))
    mockError('/api/track', 500, 'upload rejected', 'post')
    const { user } = setup(<TrackPanel folder="/data" />)

    await screen.findByText('No race track yet.')

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['hello'], 'new.fit', { type: 'application/octet-stream' })
    await user.upload(input, file)

    expect(await screen.findByText('upload rejected')).toBeInTheDocument()
  })

  it('has no accessibility violations once loaded with a track', async () => {
    mockGet('/api/track', makeTrackOverview({ present: true, distance_km: 1, bbox: [0,0,1,1], line: [[0,0], [1,1]] }))
    const { container } = setup(<TrackPanel folder="/data" />)
    await screen.findByRole('img', { name: 'Track overview' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
