import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent } from '@testing-library/react'
import { screen, setup, waitFor, within } from '../utils/render'
import StreetViewPage from '../../src/components/StreetViewPage'
import Workspace from '../../src/components/Workspace'
import { makeStreetView, makeSvSection } from '../utils/factories'
import { recordRequests } from '../utils/api'
import { server } from '../utils/server'

const serve = (sv = makeStreetView()) => server.use(http.get('/api/streetview', () => HttpResponse.json(sv)))

describe('StreetViewPage', () => {
  it('shows each stage with what it found, and a button for what is not done', async () => {
    serve(); setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByText('2 road parts, 1.1 km')).toBeInTheDocument(); expect(screen.getByText('2 sections, 9 pictures, 0.5 km')).toBeInTheDocument()
    expect(screen.getAllByText('not run yet')).toHaveLength(2); expect(screen.getByRole('button', { name: 'Redo Mapillary' })).toBeEnabled(); expect(screen.getByRole('button', { name: 'Run Panoramax' })).toBeEnabled()
    expect(screen.getByText(/never saved/)).toBeInTheDocument()
  })

  it('says which key is missing and keeps that provider from running', async () => {
    serve(makeStreetView({ keys: { mapillary: false, google: false } })); setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByText('needs MAPILLARY_TOKEN in secrets.env')).toBeInTheDocument(); expect(screen.getByText('needs GOOGLE_MAPS_API_KEY in secrets.env')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Redo Mapillary' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Run Google' })).toBeDisabled()
  })

  it('needs the road parts before a provider can run, and runs a stage when asked', async () => {
    const sv = makeStreetView(); sv.status.roads = { done: false, km: 0 }; sv.roads = null; serve(sv)
    const seen = recordRequests('/api/streetview/run'); server.use(http.post('/api/streetview/run', () => HttpResponse.json({ started: true })))
    const { user } = setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByRole('button', { name: 'Run Panoramax' })).toBeDisabled(); await user.click(screen.getByRole('button', { name: 'Run road parts' }))
    await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', stages: ['roads'], force: false })
    await user.click(screen.getByRole('button', { name: 'Run all that is missing' })); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(2)); expect(seen[1].body).toEqual({ folder: '/data', force: false })
  })

  it('shows that it is working, or why the last run failed, and refuses a second run', async () => {
    const sv = makeStreetView(); sv.job = { running: true, log: ['roads: 3 stretches'], error: '' }; serve(sv); setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByRole('status')).toHaveTextContent('working… roads: 3 stretches'); expect(screen.getByRole('button', { name: 'Run all that is missing' })).toBeDisabled()
  })

  it('shows the failure of the last run', async () => {
    const sv = makeStreetView(); sv.job = { running: false, log: [], error: 'streetview: mapillary: no MAPILLARY_TOKEN' }; serve(sv); setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no MAPILLARY_TOKEN')
  })

  it('shows a refusal to start a second run', async () => {
    serve(); server.use(http.post('/api/streetview/run', () => HttpResponse.json({ started: false, reason: 'street view is already being worked out' }))); const { user } = setup(<StreetViewPage folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Run all that is missing' })); expect(await screen.findByRole('alert')).toHaveTextContent('already being worked out')
    server.use(http.post('/api/streetview/run', () => HttpResponse.json({ detail: 'x' }, { status: 500 }))); await user.click(screen.getByRole('button', { name: 'Run all that is missing' })); await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/500|x/))
  })

  it('lists every section with its source, type, place, length, pictures, spacing, year, facing and size', async () => {
    serve(); setup(<StreetViewPage folder="/data" />)
    const rows = await screen.findAllByRole('row'); expect(rows).toHaveLength(3)
    expect(rows[1]).toHaveTextContent('Mapillary M1'); expect(rows[1]).toHaveTextContent('2D'); expect(rows[1]).toHaveTextContent('km 1.2 to 1.5'); expect(rows[1]).toHaveTextContent('300 m'); expect(rows[1]).toHaveTextContent('100 m'); expect(rows[1]).toHaveTextContent('forward 3 · back 1'); expect(rows[1]).toHaveTextContent('4000×3000')
    expect(rows[2]).toHaveTextContent('360°'); expect(rows[2]).toHaveTextContent('every way'); expect(rows[2]).toHaveTextContent('5760×2880')
  })

  it('shows the pictures of a section when its row or its marker is chosen: one for each way a flat camera faced', async () => {
    serve(); const { user } = setup(<StreetViewPage folder="/data" />)
    await user.click((await screen.findAllByRole('row'))[1])
    expect(screen.getByText(/A flat camera, facing: forward 3 · back 1/)).toBeInTheDocument()
    const imgs = screen.getAllByRole('img').filter(i => i.getAttribute('src')?.startsWith('/api/streetview/image')); expect(imgs.map(i => i.getAttribute('alt'))).toEqual(['Mapillary forward (3)', 'Mapillary back (1)'])
    expect(imgs[0].getAttribute('src')).toBe('/api/streetview/image?folder=%2Fdata&provider=mapillary&id=m2&w=256')
    await user.click(screen.getByRole('button', { name: 'Picture at back (1)' })); expect(screen.getByAltText('Larger picture').getAttribute('src')).toContain('id=m4&w=1024')
    await user.click(screen.getByText('Close the larger picture')); expect(screen.queryByAltText('Larger picture')).not.toBeInTheDocument()
  })

  it('shows the pictures of a 360° section when its marker on the map is clicked', async () => {
    serve(); setup(<StreetViewPage folder="/data" />)
    await screen.findAllByRole('row'); fireEvent.click(screen.getByTitle('Mapillary 360° km 2.1 to 2.3'))
    expect(await screen.findByText(/A 360° camera/)).toBeInTheDocument(); expect(screen.getAllByRole('img').filter(i => i.getAttribute('alt')?.startsWith('Mapillary km'))).toHaveLength(2)
    expect(screen.getByText(/Rue A|Unnamed road/)).toBeInTheDocument()
  })

  it('filters the list and the map by provider and by camera type', async () => {
    serve(); const { user } = setup(<StreetViewPage folder="/data" />)
    await screen.findAllByRole('row'); await user.click(screen.getByLabelText('360° cameras')); expect(screen.getAllByRole('row')).toHaveLength(2); expect(document.querySelector('[title^="Mapillary 360°"]')).toBeNull()
    await user.click(screen.getByLabelText(/Mapillary \(2\)/)); expect(screen.getByText('Nothing matches the filters.')).toBeInTheDocument()
  })

  it('says so when no provider has been run', async () => {
    const sv = makeStreetView(); sv.providers = { mapillary: null, panoramax: null, google: null }; serve(sv); setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByText('No street view sections yet: run a provider above.')).toBeInTheDocument()
  })

  it('marks a provider out of date when the road parts changed', async () => {
    const sv = makeStreetView(); sv.status.mapillary.stale = true; serve(sv); setup(<StreetViewPage folder="/data" />)
    expect(await screen.findByText(/out of date: the road parts changed/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Run Mapillary' })).toBeEnabled()
  })

  it('shows loading, and no map until the road parts are found', async () => {
    const sv = makeStreetView(); sv.roads = null; sv.status.roads = { done: false, km: 0 }; serve(sv); setup(<StreetViewPage folder="/data" />)
    await screen.findByText('Road parts of the run'); expect(screen.queryByRole('application')).not.toBeInTheDocument()
  })

  it('draws a Google section with its own marker', async () => {
    const sv = makeStreetView(); sv.providers.google = { sections: [makeSvSection({ id: 'G1', provider: 'google', kind: '360', angles: null, items: [{ id: 'g1', km: 1.2, lat: 50.001, lon: 5.001, b: 90 }] })], frames: 1, km: 0.3 }; sv.status.google = { done: true, stale: false, sections: 1, frames: 1, km: 0.3 }; serve(sv)
    const { user } = setup(<StreetViewPage folder="/data" />); await user.click(await screen.findByRole('button', { name: 'Google G1' }))
    expect(screen.getByAltText('Google km 1.2').getAttribute('src')).toContain('provider=google')
  })
})

describe('the Street view link', () => {
  it('is under Overview and opens the page', async () => {
    serve(); const { user } = setup(<Workspace folder="/data" onChange={() => {}} />)
    const btn = await screen.findByRole('button', { name: 'Street view' }); const overview = screen.getByRole('button', { name: 'Overview' }); expect(overview.nextElementSibling).toBe(btn)
    await user.click(btn); expect(await screen.findByRole('region', { name: 'Street view' })).toBeInTheDocument(); expect(within(screen.getByRole('region', { name: 'Street view' })).getByText('Road parts of the run')).toBeInTheDocument()
  })
})
