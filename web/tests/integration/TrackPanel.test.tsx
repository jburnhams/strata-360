import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import TrackPanel from '../../src/components/TrackPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeTrackClip, makeTrackOverview } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'
import { stubLayout } from '../utils/media'

let unstub = () => {}
beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); unstub = stubLayout() })
afterEach(() => { unstub(); vi.useRealTimers(); vi.clearAllMocks() })

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

  it('renders track metrics, the map and the charts when a track is present', async () => {
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
    expect(await screen.findByRole('application', { name: 'Race map' })).toBeInTheDocument()
    expect(await screen.findByRole('group', { name: 'Elevation chart' })).toBeInTheDocument(); expect(screen.getByRole('group', { name: 'Pace chart' })).toBeInTheDocument()
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
    await screen.findByRole('group', { name: 'Pace chart' })
    expect(await axe(container)).toHaveNoViolations()
  })

  describe('race view', () => {
    const present = () => mockGet('/api/track', makeTrackOverview({ present: true, file: 'race.fit', distance_km: 75.6 }))

    it('says how many clips are on the track and lists the ones that are not', async () => {
      present(); mockGet('/api/track/clips', { has_draft: true, clips: [makeTrackClip(), makeTrackClip({ id: 'CAM_X', label: '0001', covered: false, t_mid: undefined, lat: undefined, lon: undefined })] })
      setup(<TrackPanel folder="/data" />)
      expect(await screen.findByText(/1 clips on the track · not on the track: 0001/)).toBeInTheDocument(); expect(screen.getByText('played by the newest script draft')).toBeInTheDocument(); expect(screen.getByText('not in the film')).toBeInTheDocument()
    })

    it('shows the clip card when a chart marker is hovered and opens the clip when it is clicked', async () => {
      present(); const open = vi.fn(); const { user } = setup(<TrackPanel folder="/data" onOpenClip={open} />)
      const marker = (await screen.findAllByRole('button', { name: 'Clip 0023' }))[0]
      await user.hover(marker); const card = await screen.findByRole('tooltip'); expect(card).toHaveTextContent('clip 0023'); expect(card).toHaveTextContent('in the film · 16.5 s'); expect(card).toHaveTextContent('km 12.3 (16%)')
      await user.unhover(marker); await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())
      await user.click(marker); expect(open).toHaveBeenCalledWith('CAM_20260222190000_0023_D')
    })

    it('switches the horizontal axis between time and distance', async () => {
      present(); const { user } = setup(<TrackPanel folder="/data" />)
      const sel = await screen.findByLabelText('Horizontal axis'); expect(sel).toHaveValue('time')
      await user.selectOptions(sel, 'km'); expect(await screen.findAllByText(/^\d+ km$/)).not.toHaveLength(0)
    })

    it('says so when the map data cannot be loaded, and still shows the numbers', async () => {
      present(); mockError('/api/track/series', 404, 'no race track')
      setup(<TrackPanel folder="/data" />)
      expect(await screen.findByText(/The map and charts need the track and its clips/)).toBeInTheDocument(); expect(screen.getByText('Distance')).toBeInTheDocument()
    })
  })
})
