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
})
