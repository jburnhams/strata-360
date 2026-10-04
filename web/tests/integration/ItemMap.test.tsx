import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, setup, waitFor } from '../utils/render'
import TrackMap from '../../src/components/TrackMap'
import PhotoPage from '../../src/components/PhotoPage'
import GapView from '../../src/components/GapView'
import { makeGap, makePhoto, makeTracksListing } from '../utils/factories'
import { recordRequests } from '../utils/api'
import { server } from '../utils/server'

const line = { lat: [50.0, 50.01, 50.02], lon: [5.0, 5.01, 5.02], t: [0, 100, 200] }
describe('the race map on the page of a film item', () => {
  it('draws the run, the routes and the markers, and asks for just the part of the run the item covers', async () => {
    const seen = recordRequests('/api/track/line'); server.use(http.get('/api/track/line', () => HttpResponse.json(line)), http.get('/api/tracks', () => HttpResponse.json(makeTracksListing())))
    setup(<TrackMap folder="/data" span={[1000, 2000]} label="Gap G01" />)
    expect(await screen.findByRole('application', { name: /Map of the route/ })).toBeInTheDocument(); expect(screen.getByText('the part of the run this covers')).toBeInTheDocument()
    await waitFor(() => expect(seen.some(r => r.url.searchParams.get('t0') === '1000' && r.url.searchParams.get('t1') === '2000')).toBe(true)); expect(seen.some(r => !r.url.searchParams.get('t0'))).toBe(true)          // (the whole run too)
    expect(screen.getByRole('button', { name: 'Reset the view' })).toBeInTheDocument(); expect(await screen.findByRole('button', { name: 'Zoom to this' })).toBeInTheDocument()
  })

  it('shows a single place for a photo, and says when a photo is not on the run', async () => {
    server.use(http.get('/api/track/line', () => HttpResponse.json(line)), http.get('/api/tracks', () => HttpResponse.json(makeTracksListing())))
    const { unmount } = setup(<PhotoPage folder="/data" photo={makePhoto({ use: true })} tz="UTC" onChanged={() => {}} />)
    expect(await screen.findByText('where it was taken')).toBeInTheDocument(); expect(screen.getByText('Where on the route')).toBeInTheDocument(); unmount()
    setup(<PhotoPage folder="/data" photo={makePhoto({ use: true, loc: null, track: null })} tz="UTC" onChanged={() => {}} />); expect(screen.getByText(/not on the run/)).toBeInTheDocument()
  })

  it('is on the gap page for the time of the gap', async () => {
    const seen = recordRequests('/api/track/line'); server.use(http.get('/api/track/line', () => HttpResponse.json(line)), http.get('/api/tracks', () => HttpResponse.json(makeTracksListing())), http.get('/api/gaps', () => HttpResponse.json({ gaps: [makeGap({ id: 'G01', t0: 5000, t1: 9000 })], flyover: { available: true, note: '' } })))
    setup(<GapView folder="/data" gap="G01" />); expect(await screen.findByText('Where on the route')).toBeInTheDocument(); await waitFor(() => expect(seen.some(r => r.url.searchParams.get('t0') === '5000' && r.url.searchParams.get('t1') === '9000')).toBe(true))
  })

  it('says on the page of a clip, a gap, a photo or a street view section when the runner stopped during it, with the details', async () => {
    const pois = [{ name: 'Stop 4', lat: 50, lon: 5, ele: null, sym: 'stop', desc: 'km 114.9 of the run', track: '', key: 'k4', added: true, gap: 'G05', stop: { arrived: 5000, left: 8120, stopped_s: 3120, radius_m: 60 } },
      { name: 'Stop 5', lat: 50, lon: 5, ele: null, sym: 'stop', desc: 'km 300 of the run', track: '', key: 'k5', added: false, stop: { arrived: 90000, left: 90700, stopped_s: 700, radius_m: 60 } }]
    server.use(http.get('/api/track/line', () => HttpResponse.json(line)), http.get('/api/tracks', () => HttpResponse.json(makeTracksListing({ pois }))))
    const { unmount } = setup(<TrackMap folder="/data" tz="UTC" span={[6000, 7000]} label="Clip 0023" />)
    const box = await screen.findByLabelText('Stops here'); expect(box).toHaveTextContent('The runner stopped here'); expect(box).toHaveTextContent('Stop 4'); expect(box).toHaveTextContent('52 min'); expect(box).toHaveTextContent('km 114.9'); expect(box).toHaveTextContent('in the video as G05'); expect(box).not.toHaveTextContent('Stop 5'); unmount()
    const { unmount: u2 } = setup(<TrackMap folder="/data" tz="UTC" point={{ lat: 50, lon: 5 }} at={7000} label="Photo P1" />); expect(await screen.findByLabelText('Stops here')).toHaveTextContent('Stop 4'); u2()
    setup(<TrackMap folder="/data" tz="UTC" span={[20000, 21000]} label="Gap" />); await screen.findByLabelText('Where on the route'); expect(screen.queryByLabelText('Stops here')).toBeNull()
  })
})
