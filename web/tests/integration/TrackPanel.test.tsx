import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import TrackPanel from '../../src/components/TrackPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeTrackClip, makeTrackEntry, makeTrackOverview, makeTracksListing } from '../utils/factories'
import { mockGet, mockPost, mockDelete, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'
import { http, HttpResponse } from 'msw'
import { server } from '../utils/server'

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

  it('shows the map credit when the background is on, and says why it is off when it is not', async () => {
    mockGet('/api/track', makeTrackOverview({ present: true, file: 't.fit', bbox: [40, 10, 41, 11], line: [[40, 10], [41, 11]] }))
    const { unmount } = setup(<TrackPanel folder="/data" />)
    expect(await screen.findByText(/Maps © Thunderforest/)).toBeInTheDocument(); expect(screen.queryByText(/map background is off/)).not.toBeInTheDocument(); unmount()
    mockGet('/api/tiles/status', { ok: false, style: 'tf-landscape', error: 'the map style tf-landscape needs a key: put THUNDERFOREST_API_KEY=... in secrets.env' })
    setup(<TrackPanel folder="/data" />)
    expect(await screen.findByText(/The map background is off: the map style tf-landscape needs a key/)).toBeInTheDocument(); expect(screen.getByRole('application', { name: 'Race map' })).toBeInTheDocument()
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

  describe('tracks list', () => {
    const present = () => mockGet('/api/track', makeTrackOverview({ present: true, file: 'race.fit', distance_km: 75.6 }))
    const two = () => makeTracksListing({ runs: 1, divergences: [{ lat: 50.05, lon: 5.07, peak_m: 120, length_m: 300, km: 5, t: 0, line: [[50.04, 5.06], [50.06, 5.08]] }], tracks: [makeTrackEntry(), makeTrackEntry({ id: 't2', name: 'course.gpx', kind: 'route', timed: false, start_utc: null, pois: 2, distance_km: 80 })], pois: [{ name: 'Aid 1', lat: 50.05, lon: 5.07, ele: 120, sym: '', desc: '', track: 't2' }] })

    it('lists each track with its kind, and shows routes on the map with their points of interest', async () => {
      present(); mockGet('/api/tracks', two()); mockGet('/api/tracks/line', { id: 't2', lat: [50, 50.1], lon: [5, 5.1] })
      setup(<TrackPanel folder="/data" />)
      expect(await screen.findByLabelText('Kind of course.gpx')).toHaveValue('route'); expect(screen.getByLabelText('Kind of race.gpx')).toHaveValue('run')
      expect(screen.getByText(/80 km · no times · 2 POI/)).toBeInTheDocument()
      expect(await screen.findByText(/run leaves the route by over 50 m \(the 1 farthest\)/)).toBeInTheDocument();
      expect(await screen.findByText('route (planning only)')).toBeInTheDocument(); expect(screen.getByText('point of interest')).toBeInTheDocument()
      await waitFor(() => expect(document.querySelector('[data-poi]')).not.toBeNull())
    })

    it('marks a track a run, refreshing the race track and the list', async () => {
      present(); const seen = recordRequests('/api/tracks/kind'); let marked = false
      const after = makeTracksListing({ runs: 2, tracks: [makeTrackEntry(), makeTrackEntry({ id: 't2', name: 'course.gpx', kind: 'run' })], merged: { runs: ['main', 't2'], samples: 200, start_utc: '', end_utc: '', distance_km: 90 } })
      mockGet('/api/tracks', () => (marked ? after : two())); mockPost('/api/tracks/kind', () => { marked = true; return after })
      const { user } = setup(<TrackPanel folder="/data" />)
      await user.selectOptions(await screen.findByLabelText('Kind of course.gpx'), 'run')
      expect(await screen.findByText(/Race track = 2 runs merged · 90 km/)).toBeInTheDocument(); expect(seen.at(-1)?.body).toMatchObject({ folder: '/data', id: 't2', kind: 'run' })
    })

    it('adds several files one after the other and says which one was refused', async () => {
      present(); mockGet('/api/tracks', makeTracksListing()); const seen = recordRequests('/api/tracks')
      server.use(http.post('/api/tracks', ({ request }) => new URL(request.url).searchParams.get('filename') === 'bad.gpx' ? HttpResponse.json({ detail: 'could not read that file' }, { status: 400 }) : HttpResponse.json(makeTrackEntry())))
      const { user } = setup(<TrackPanel folder="/data" />)
      await user.upload(await screen.findByLabelText('Add track files'), [new File(['a'], 'a.gpx'), new File(['b'], 'bad.gpx'), new File(['c'], 'c.gpx')])
      expect(await screen.findByRole('alert')).toHaveTextContent('bad.gpx: could not read that file')
      expect(seen.filter(r => r.method === 'POST').map(r => r.url.searchParams.get('filename'))).toEqual(['a.gpx', 'bad.gpx'])
    })

    it('removes a track', async () => {
      present(); mockGet('/api/tracks', two()); mockDelete('/api/tracks', makeTracksListing({ runs: 1, tracks: [makeTrackEntry()] })); const seen = recordRequests('/api/tracks')
      const { user } = setup(<TrackPanel folder="/data" />)
      await user.click(await screen.findByRole('button', { name: 'Remove course.gpx' }))
      await waitFor(() => expect(seen.some(r => r.method === 'DELETE' && r.url.searchParams.get('id') === 't2')).toBe(true))
    })
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
