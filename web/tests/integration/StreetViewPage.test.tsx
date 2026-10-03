import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent } from '@testing-library/react'
import { screen, setup, waitFor, within } from '../utils/render'
import StreetViewPage, { DEFAULT_FILTERS, SHOW_ALL, dur, nearText, passes, rampColour, when } from '../../src/components/StreetViewPage'
import Workspace from '../../src/components/Workspace'
import { makeNearItem, makeNearResult, makeStreetView, makeSvSection, makeTrackClip, makeTrackEntry, makeTracksListing } from '../utils/factories'
import { recordRequests } from '../utils/api'
import { server } from '../utils/server'

const serve = (sv = makeStreetView()) => server.use(http.get('/api/streetview', () => HttpResponse.json(sv)))

describe('StreetViewPage', () => {
  it('shows each stage with what it found, and a button for what is not done', async () => {
    serve(); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByText('2 road parts, 1.1 km')).toBeInTheDocument(); expect(screen.getByText('2 sections, 9 pictures, 0.5 km')).toBeInTheDocument()
    expect(screen.getAllByText('not run yet')).toHaveLength(3); expect(screen.getByRole('button', { name: 'Run quality check' })).toBeEnabled(); expect(screen.getByRole('button', { name: 'Redo Mapillary' })).toBeEnabled(); expect(screen.getByRole('button', { name: 'Run Panoramax' })).toBeEnabled()
  })

  it('says which key is missing and keeps that provider from running', async () => {
    serve(makeStreetView({ keys: { mapillary: false, google: false } })); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByText('needs MAPILLARY_TOKEN in secrets.env')).toBeInTheDocument(); expect(screen.getByText('needs GOOGLE_MAPS_API_KEY in secrets.env')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Redo Mapillary' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Run Google' })).toBeDisabled()
  })

  it('needs the road parts before a provider can run, and runs a stage when asked', async () => {
    const sv = makeStreetView(); sv.status.roads = { done: false, km: 0 }; sv.roads = null; serve(sv)
    const seen = recordRequests('/api/streetview/run'); server.use(http.post('/api/streetview/run', () => HttpResponse.json({ started: true })))
    const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByRole('button', { name: 'Run Panoramax' })).toBeDisabled(); await user.click(screen.getByRole('button', { name: 'Run road parts' }))
    await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', stages: ['roads'], force: false })
    await user.click(screen.getByRole('button', { name: 'Run all that is missing' })); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(2)); expect(seen[1].body).toEqual({ folder: '/data', force: false })
  })

  it('shows that it is working, or why the last run failed, and refuses a second run', async () => {
    const sv = makeStreetView(); sv.job = { running: true, log: ['roads: 3 stretches'], error: '' }; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByRole('status')).toHaveTextContent('working… roads: 3 stretches'); expect(screen.getByRole('button', { name: 'Run all that is missing' })).toBeDisabled()
  })

  it('shows the failure of the last run', async () => {
    const sv = makeStreetView(); sv.job = { running: false, log: [], error: 'streetview: mapillary: no MAPILLARY_TOKEN' }; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no MAPILLARY_TOKEN')
  })

  it('shows a refusal to start a second run', async () => {
    serve(); server.use(http.post('/api/streetview/run', () => HttpResponse.json({ started: false, reason: 'street view is already being worked out' }))); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    await user.click(await screen.findByRole('button', { name: 'Run all that is missing' })); expect(await screen.findByRole('alert')).toHaveTextContent('already being worked out')
    server.use(http.post('/api/streetview/run', () => HttpResponse.json({ detail: 'x' }, { status: 500 }))); await user.click(screen.getByRole('button', { name: 'Run all that is missing' })); await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/500|x/))
  })

  it('lists every section with its source, type, place, length, pictures, spacing, year, facing and size', async () => {
    serve(); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const rows = await screen.findAllByRole('row'); expect(rows).toHaveLength(3)
    expect(rows[1]).toHaveTextContent('Mapillary M1'); expect(rows[1]).toHaveTextContent('2D'); expect(rows[1]).toHaveTextContent('km 1.2 to 1.5'); expect(rows[1]).toHaveTextContent('300 m'); expect(rows[1]).toHaveTextContent('100 m'); expect(rows[1]).toHaveTextContent('forward 3 · back 1'); expect(rows[1]).toHaveTextContent('4000×3000')
    expect(rows[2]).toHaveTextContent('360°'); expect(rows[2]).toHaveTextContent('every way'); expect(rows[2]).toHaveTextContent('5760×2880')
  })

  it('shows the pictures of a section when its row or its marker is chosen: one for each way a flat camera faced', async () => {
    serve(); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    await user.click((await screen.findAllByRole('row'))[1])
    expect(screen.getByText(/A flat camera, facing: forward 3 · back 1/)).toBeInTheDocument()
    const imgs = screen.getAllByRole('img').filter(i => /^Mapillary (forward|back)/.test(i.getAttribute('alt') ?? '')); expect(imgs.map(i => i.getAttribute('alt'))).toEqual(['Mapillary forward (3)', 'Mapillary back (1)'])
    expect(imgs[0].getAttribute('src')).toBe('/api/streetview/image?folder=%2Fdata&provider=mapillary&id=m2&w=256')
    await user.click(screen.getByRole('button', { name: 'Picture at back (1)' })); expect(screen.getByAltText('Larger picture').getAttribute('src')).toContain('id=m4&w=1024')
    await user.click(screen.getByText('Close the larger picture')); expect(screen.queryByAltText('Larger picture')).not.toBeInTheDocument()
  })

  it('shows the pictures of a 360° section when its marker on the map is clicked', async () => {
    serve(); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    await screen.findAllByRole('row'); fireEvent.click(await screen.findByTitle('Mapillary 360° km 2.1 to 2.3'))
    expect(await screen.findByText(/A 360° camera/)).toBeInTheDocument(); expect(screen.getAllByRole('img').filter(i => i.getAttribute('alt')?.startsWith('Mapillary km'))).toHaveLength(2)
    expect(screen.getByText(/Rue A|Unnamed road/)).toBeInTheDocument()
  })

  it('filters the list and the map by provider and by camera type', async () => {
    serve(); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    await screen.findAllByRole('row'); await user.click(screen.getByLabelText('360° cameras')); expect(screen.getAllByRole('row')).toHaveLength(2); expect(document.querySelector('[title^="Mapillary 360°"]')).toBeNull()
    await user.click(screen.getByLabelText(/Mapillary \(2\)/)); expect(screen.getByText('Nothing matches the filters.')).toBeInTheDocument()
  })

  it('says so when no provider has been run', async () => {
    const sv = makeStreetView(); sv.providers = { mapillary: null, panoramax: null, google: null }; sv.sections = []; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByText('No street view sections yet: run a provider above.')).toBeInTheDocument()
  })

  it('marks a provider out of date when the road parts changed', async () => {
    const sv = makeStreetView(); sv.status.mapillary.stale = true; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByText(/out of date: the road parts changed/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Run Mapillary' })).toBeEnabled()
  })

  it('shows loading, and no map until the road parts are found', async () => {
    const sv = makeStreetView(); sv.roads = null; sv.status.roads = { done: false, km: 0 }; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    await screen.findByText('Road parts of the run'); expect(screen.queryByRole('application')).not.toBeInTheDocument()
  })

  it('draws a Google section with its own marker', async () => {
    const sv = makeStreetView(); sv.providers.google = { frames: 1, km: 0.3 }; sv.sections.push(makeSvSection({ id: 'G1', key: 'google:g:1.20', plausible: false, why_not: "Google's terms do not allow its pictures in a film", provider: 'google', kind: '360', angles: null, items: [{ id: 'g1', km: 1.2, lat: 50.001, lon: 5.001, b: 90 }] })); sv.status.google = { done: true, stale: false, sections: 1, frames: 1, km: 0.3 }; serve(sv)
    const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await user.click(await screen.findByRole('button', { name: 'Google G1' }))
    expect(screen.getByAltText('Google km 1.2').getAttribute('src')).toContain('provider=google')
  })
})

describe('the sections that could be used in the film', () => {
  it('lists only the plausible sections, with details, previews and a count of the rest', async () => {
    serve(); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const card = await screen.findByLabelText('Sections that could be used'); expect(within(card).getAllByRole('listitem').filter(l => l.hasAttribute('data-section'))).toHaveLength(1)
    const m1 = card.querySelector('[data-section="M1"]')!; expect(m1).toHaveTextContent('Mapillary M1 · 2D'); expect(m1).toHaveTextContent('km 1.2 to 1.5'); expect(m1).toHaveTextContent('300 m of road that matches the run'); expect(m1).toHaveTextContent('steadied: by matching only (may still wobble)'); expect(m1).toHaveTextContent('4 pictures, one every 100 m'); expect(m1).toHaveTextContent('clip of 2 to 1 s (the longest is 4 pictures a second blended up to 30 frames a second; a shorter one is the same road played faster)'); expect(m1).toHaveTextContent('faces forward 3 · back 1')
    expect(within(m1 as HTMLElement).getAllByRole('img').length).toBeGreaterThanOrEqual(2); expect(card).toHaveTextContent('1 of 2 sections have enough pictures'); expect(card).toHaveTextContent('1 more sections are too short or too sparse')
  })

  it('saves the choice made for a section: not used, possible or must include', async () => {
    const sv = makeStreetView(); sv.sections[0].choice = 'possible'; serve(sv); const seen = recordRequests('/api/streetview/choice'); server.use(http.post('/api/streetview/choice', () => HttpResponse.json({ key: 'mapillary:s1:1.20', choice: 'must' })))
    const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); const group = await screen.findByRole('group', { name: 'Use Mapillary M1 in the film' })
    expect(within(group).getByLabelText('Possible')).toBeChecked(); expect(within(group).getByLabelText('Not used')).not.toBeChecked()
    await user.click(within(group).getByLabelText('Must include')); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', key: 'mapillary:s1:1.20', choice: 'must' })
    await user.click(within(group).getByLabelText('Not used')); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(2)); expect(seen[1].body).toMatchObject({ choice: 'none' })
  })

  it('says when sections over the same road come from different sources, in the cards and in the list', async () => {
    const sv = makeStreetView(); sv.sections[0].overlaps = ['P1']; sv.sections.push(makeSvSection({ id: 'P1', key: 'panoramax:c:1.25', provider: 'panoramax', kind: '360', angles: null, km0: 1.25, km1: 1.45, length_m: 200, overlaps: ['M1'], items: [{ id: 'p1', km: 1.3, lat: 50.001, lon: 5.0025, b: 90 }] })); serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const note = (await screen.findAllByRole('note'))[0]; expect(note).toHaveTextContent('Overlaps the same road as Panoramax P1 (km 1.25 to 1.45)'); expect(screen.getAllByRole('note')).toHaveLength(2)
    const rows = screen.getAllByRole('row'); expect(rows[1]).toHaveTextContent('P1'); expect(within(rows[1]).getByText('P1')).toHaveClass('text-amber-700')
  })

  it('warns when a daytime view is for a stretch run in the dark, and still lets you choose it', async () => {
    const sv = makeStreetView(); sv.sections[0].light = { captured: 'day', race: 'night', warning: 'Filmed in daylight, but the runner passes here at night: it would look wrong in the film.' }; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const w = await screen.findByText(/Filmed in daylight, but the runner passes here at night/); expect(w).toHaveAttribute('data-light'); expect(screen.getByLabelText('Must include')).toBeEnabled()
  })

  it('shows no light warning when the light fits', async () => {
    const sv = makeStreetView(); sv.sections[0].light = { captured: 'day', race: 'day', warning: null }; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    await screen.findByLabelText('Sections that could be used'); expect(document.querySelector('[data-light]')).toBeNull()
  })

  it('shows how good a clip of each section will look, with the measurements, and when it has not been checked or could not be', async () => {
    const sv = makeStreetView(); sv.sections[0].quality = { score: 78, grade: 'good', psnr: 16.4, jerk: 0.19, roll: 0.18 }; sv.sections.push(makeSvSection({ id: 'M3', key: 'mapillary:s3:3.00', km0: 3.0, km1: 3.3, quality: { score: 9, grade: 'poor', psnr: 12.9, jerk: 2.9, roll: 5.3 } }),
      makeSvSection({ id: 'M4', key: 'mapillary:s4:4.00', km0: 4.0, km1: 4.3, quality: { score: null, grade: null, error: 'RuntimeError: x' } })); serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const good = await screen.findByText('quality: good (78)'); expect(good).toHaveAttribute('title', 'in-between pictures 16.4 dB · unsteadiness 0.19° · turning 0.18°'); expect(screen.getByText('quality: poor (9)')).toBeInTheDocument()
    expect(screen.getByText('quality could not be measured')).toHaveAttribute('title', 'RuntimeError: x'); sv.sections[0].quality = null
  })

  it('lists every candidate best quality first (the unscored last), or along the route, and shows the score in the table too', async () => {
    const sv = makeStreetView(); sv.sections = [makeSvSection({ id: 'M1', key: 'a', km0: 1, km1: 1.3, quality: { score: 40, grade: 'fair', psnr: 14, jerk: 1, roll: 1 } }), makeSvSection({ id: 'M2', key: 'b', km0: 2, km1: 2.3, quality: null }),
      makeSvSection({ id: 'M3', key: 'c', km0: 3, km1: 3.3, quality: { score: 80, grade: 'good', psnr: 17, jerk: 0.1, roll: 0.1 } }), makeSvSection({ id: 'M4', key: 'd', km0: 4, km1: 4.3, plausible: false, why_not: 'only 5 pictures (needs 30)' })]; serve(sv)
    const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); const card = await screen.findByLabelText('Sections that could be used'); const ids = () => [...card.querySelectorAll('[data-section]')].map(e => e.getAttribute('data-section'))
    expect(ids()).toEqual(['M3', 'M1', 'M2']); await user.selectOptions(within(card).getByLabelText('Order'), 'route'); expect(ids()).toEqual(['M1', 'M2', 'M3'])
    const rows = screen.getAllByRole('row'); expect(within(rows[1]).getByText('fair (40)')).toBeInTheDocument(); expect(within(rows[3]).getByText('good (80)')).toBeInTheDocument(); expect(card).toHaveTextContent('1 more sections are too short or too sparse')
  })

  it('says the quality has not been checked yet', async () => {
    serve(); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); expect(await screen.findByText('quality not checked yet')).toBeInTheDocument()
  })

  it('reports a failure to save the choice', async () => {
    serve(); server.use(http.post('/api/streetview/choice', () => HttpResponse.json({ detail: 'no such street view section' }, { status: 404 })))
    const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await user.click(await screen.findByLabelText('Possible')); expect(await screen.findByRole('alert')).toHaveTextContent(/404|no such/)
  })

  it('says so when no section has enough pictures', async () => {
    const sv = makeStreetView(); sv.sections.forEach(s => { s.plausible = false }); serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    expect(await screen.findByText('None of the sections found has enough pictures yet.')).toBeInTheDocument()
  })
})

describe('duration colours and the camera clips on the map', () => {
  it('colours a duration on a log scale from light yellow (short) to dark purple (long)', () => {
    expect(rampColour(1, 1, 100)).toBe('#fde725'); expect(rampColour(100, 1, 100)).toBe('#440154'); expect(rampColour(0.1, 1, 100)).toBe('#fde725'); expect(rampColour(1000, 1, 100)).toBe('#440154')
    expect(rampColour(10, 1, 100)).not.toBe(rampColour(30, 1, 100)); expect(rampColour(5, 5, 5)).toMatch(/^#[0-9a-f]{6}$/); expect(dur(45)).toBe('45 s'); expect(dur(215)).toBe('4 min'); expect(dur(7200)).toBe('2.0 h')
  })

  it('draws a numbered marker and a coloured stretch for each camera clip, and the sections coloured by the longest clip they can make', async () => {
    const sv = makeStreetView(); sv.sections[0].max_s = 60; serve(sv)
    server.use(http.get('/api/track/clips', () => HttpResponse.json({ clips: [makeTrackClip({ label: '0023', duration_s: 5 }), makeTrackClip({ id: 'b', label: '0024', duration_s: 300, stretch: [[50.1, 5.1], [50.11, 5.11]], lat: 50.105, lon: 5.105 }), makeTrackClip({ id: 'c', label: '0025', covered: false })], has_draft: false })))
    setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); const a = await screen.findByTitle('Clip 0023 · 5 s'); expect(a).toBeInTheDocument(); expect(screen.getByTitle('Clip 0024 · 5 min')).toBeInTheDocument(); expect(screen.queryByTitle(/Clip 0025/)).toBeNull()
    const markers = [...document.querySelectorAll('[data-clip-marker]')] as HTMLElement[]; expect(markers.map(m => m.textContent)).toEqual(['0023', '0024']); expect(markers[0].getAttribute('style')).toContain(`background:${rampColour(5, 1, 300)}`); expect(markers[1].getAttribute('style')).toContain(`background:${rampColour(300, 1, 300)}`)
    const legend = screen.getByLabelText('Duration colours'); expect(legend).toHaveTextContent('1 s'); expect(legend).toHaveTextContent('5 min'); expect(legend).toHaveTextContent('numbered stretches are the camera clips')
  })

  it('hides the camera clips when their box is cleared', async () => {
    serve(); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findByTitle(/Clip 0023/); await user.click(screen.getByLabelText('Camera clips')); expect(screen.queryByTitle(/Clip 0023/)).toBeNull()
  })
})

describe('filtering by quality factors', () => {
  const mixed = () => {
    const sv = makeStreetView(); const q = (score: number | null, grade: 'good' | 'fair' | 'poor' | null) => (score == null ? null : { score, grade, psnr: 15, jerk: 0.2, roll: 0.2 })
    sv.sections = [makeSvSection({ id: 'M1', key: 'a', km0: 1, quality: q(80, 'good'), steadied: 'exact' }), makeSvSection({ id: 'M2', key: 'b', km0: 2, quality: q(50, 'fair'), steadied: 'estimated' }),
      makeSvSection({ id: 'M3', key: 'c', km0: 3, quality: q(9, 'poor'), steadied: 'by matching only', light: { captured: 'day', race: 'night', warning: 'Filmed in daylight, but the runner passes here at night: it would look wrong in the film.' } }),
      makeSvSection({ id: 'M4', key: 'd', km0: 4, quality: null, steadied: 'estimated', plausible: false, why_not: 'only 5 pictures (needs 30)' })]; return sv
  }
  const ids = () => [...document.querySelectorAll('tbody tr')].map(r => r.querySelector('td button')?.textContent?.replace('Mapillary ', ''))

  it('has a Filters drop down with boxes for the quality, the steadiness, the light and usable sections, all on at first', async () => {
    serve(mixed()); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); expect(screen.queryByRole('group', { name: 'Filters' })).toBeNull()
    await user.click(screen.getByRole('button', { name: /Filters/ })); const g = screen.getByRole('group', { name: 'Filters' })
    for (const l of ['Good', 'Fair', 'Poor', 'Not checked', 'Exact (360°, true rotation)', 'Estimated (360°, levelled from the picture)', 'By matching only (flat camera)', 'Light fits the race', 'Daytime view for a night stretch (or the reverse)']) expect(within(g).getByLabelText(l)).toBeChecked()
    expect(within(g).getByLabelText('Only sections with enough pictures to make a clip')).not.toBeChecked(); expect(screen.getByText('4 of 4 sections shown')).toBeInTheDocument()
  })

  it('hides the sections of an unchecked quality, in the list, the candidates and the count', async () => {
    serve(mixed()); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); expect(ids()).toEqual(['M1', 'M2', 'M3', 'M4'])
    await user.click(screen.getByRole('button', { name: /Filters/ })); await user.click(screen.getByLabelText('Poor')); expect(ids()).toEqual(['M1', 'M2', 'M4']); expect(screen.getByText('3 of 4 sections shown')).toBeInTheDocument(); expect(document.querySelector('[data-section="M3"]')).toBeNull()
    await user.click(screen.getByLabelText('Not checked')); expect(ids()).toEqual(['M1', 'M2']); expect(screen.getByRole('button', { name: /Filters \(2\)/ })).toBeInTheDocument()
    await user.click(screen.getByText('Show everything')); expect(ids()).toEqual(['M1', 'M2', 'M3', 'M4'])
  })

  it('filters by how steady the camera is kept, by the light and by usable', async () => {
    serve(mixed()); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); await user.click(screen.getByRole('button', { name: /Filters/ }))
    await user.click(screen.getByLabelText('By matching only (flat camera)')); expect(ids()).toEqual(['M1', 'M2', 'M4']); await user.click(screen.getByLabelText('By matching only (flat camera)'))
    await user.click(screen.getByLabelText('Daytime view for a night stretch (or the reverse)')); expect(ids()).toEqual(['M1', 'M2', 'M4']); await user.click(screen.getByLabelText('Daytime view for a night stretch (or the reverse)'))
    await user.click(screen.getByLabelText('Exact (360°, true rotation)')); expect(ids()).toEqual(['M2', 'M3', 'M4']); await user.click(screen.getByLabelText('Exact (360°, true rotation)'))
    await user.click(screen.getByLabelText('Only sections with enough pictures to make a clip')); expect(ids()).toEqual(['M1', 'M2', 'M3'])
  })

  it('says when no candidate matches the filters', async () => {
    serve(mixed()); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); await user.click(screen.getByRole('button', { name: /Filters/ }))
    for (const l of ['Good', 'Fair', 'Poor', 'Not checked']) await user.click(screen.getByLabelText(l))
    expect(screen.getByText('No candidate matches the filters.')).toBeInTheDocument(); expect(screen.getByText('Nothing matches the filters.')).toBeInTheDocument()
  })

  it('has a pure rule for what passes', () => {
    const s = makeSvSection({ quality: { score: 80, grade: 'good', psnr: 1 }, steadied: 'exact' }); expect(passes(s, DEFAULT_FILTERS)).toBe(true); expect(passes(s, { ...DEFAULT_FILTERS, 'q:good': false })).toBe(false)
    expect(passes({ ...s, plausible: false }, { ...DEFAULT_FILTERS, plausible: true })).toBe(false); expect(passes({ ...s, light: { captured: 'day', race: 'night', warning: 'x' } }, { ...DEFAULT_FILTERS, 'l:warn': false })).toBe(false)
  })
})

describe('when each section was filmed and when the runner passed it', () => {
  it('writes the time in the race time zone', () => {
    expect(when(1_709_812_800, 'UTC')).toBe('Thu 7 Mar 2024 12:00'); expect(when(1_709_812_800, 'Europe/Brussels')).toBe('Thu 7 Mar 2024 13:00'); expect(when(null, 'UTC')).toBe('–'); expect(when(1_709_812_800, 'No/Such_Zone')).toBe('2024-03-07 12:00')
  })

  it('shows both times on each candidate, in the detail and in the table', async () => {
    const sv = makeStreetView(); sv.sections[0].filmed = [1_709_812_800, 1_709_812_830]; sv.sections[0].passed = [1_771_754_460, 1_771_754_700]; serve(sv)
    const { user } = setup(<StreetViewPage folder="/data" tz="UTC" />); const card = (await screen.findByLabelText('Sections that could be used')).querySelector('[data-section="M1"] [data-times]')!
    expect(card).toHaveTextContent('Filmed Thu 7 Mar 2024 12:00 · you pass it Sun 22 Feb 2026 10:01')
    const row = screen.getAllByRole('row')[1]; expect(row).toHaveTextContent('Thu 7 Mar 2024 12:00'); expect(row).toHaveTextContent('Sun 22 Feb 2026 10:01'); expect(screen.getByText('You passed')).toBeInTheDocument(); expect(screen.getByText('Filmed')).toBeInTheDocument()
    await user.click(row); const detail = document.querySelectorAll('[data-times]'); expect([...detail].some(d => d.textContent?.includes('you pass it Sun 22 Feb 2026 10:01 to 10:05'))).toBe(true)
  })
})

describe('the run and the route tracks on the map', () => {
  const paths = (colour: string) => [...document.querySelectorAll(`path[stroke="${colour}"]`)]

  it('draws the run in red, thick, over the road parts, and the route tracks in blue under it', async () => {
    serve(); server.use(http.get('/api/tracks', () => HttpResponse.json(makeTracksListing({ tracks: [makeTrackEntry({ id: 'main', kind: 'run' }), makeTrackEntry({ id: 'r1', name: 'course.gpx', kind: 'route' }), makeTrackEntry({ id: 'r2', kind: 'route', error: 'broken' })], runs: 1 }))))
    const seen = recordRequests('/api/tracks/line'); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await waitFor(() => expect(paths('#2563eb').length).toBeGreaterThan(0))
    expect(paths('#dc2626').some(p => p.getAttribute('stroke-width') === '4')).toBe(true); expect(paths('#2563eb')[0].getAttribute('stroke-width')).toBe('5'); expect(paths('#78716c')).toHaveLength(0)         // (the grey line is gone)
    expect(seen.map(r => r.url.searchParams.get('id'))).toEqual(['r1'])                                                                           // only the route without an error
    const all = [...document.querySelectorAll('path')]; const idx = (c: string) => all.findIndex(p => p.getAttribute('stroke') === c); expect(idx('#2563eb')).toBeLessThan(idx('#f59e0b')); expect(idx('#f59e0b')).toBeLessThan(idx('#dc2626'))                    // routes, then the road parts, then the run on top
    expect(screen.getByText('the run')).toBeInTheDocument(); expect(screen.getByText('route tracks')).toBeInTheDocument()
  })

  it('has no blue and no route legend when there are no routes', async () => {
    serve(); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); await waitFor(() => expect(paths('#dc2626').length).toBeGreaterThan(0)); expect(paths('#2563eb')).toHaveLength(0); expect(screen.queryByText('route tracks')).toBeNull()
  })
})

describe('clicking the map for the nearest street view', () => {
  const click = async () => { serve(); const r = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); fireEvent.click(await screen.findByRole('application'), { clientX: 40, clientY: 30 }); return r }

  it('asks for the nearest street view at the clicked place and lists what each provider has, with the rules that rule each out', async () => {
    const seen = recordRequests('/api/streetview/near'); server.use(http.get('/api/streetview/near', () => HttpResponse.json({ cached: true, result: makeNearResult(), job: null })))
    await click(); const panel = await screen.findByLabelText('Nearest street view to the clicked point'); await waitFor(() => expect(seen.filter(r => r.method === 'GET')).toHaveLength(1))
    const u = seen[0].url.searchParams; expect(u.get('folder')).toBe('/data'); expect(Number.isFinite(Number(u.get('lat')))).toBe(true); expect(seen.filter(r => r.method === 'POST')).toHaveLength(0)         // a click fetches nothing
    const m = within(await screen.findByRole('region', { name: 'Mapillary near the point' })); const item = m.getByText(/12.5 m away · 360°/).closest('[data-near-item]') as HTMLElement
    expect(item).toHaveTextContent('GoPro Max · 5760×2880'); expect(item).toHaveTextContent('Ruled out: 1 reason'); expect(item.querySelector('img')!.getAttribute('src')).toBe('/api/streetview/near/image?folder=%2Fdata&provider=mapillary&id=m9&w=256')
    const rules = [...item.querySelectorAll('[data-rule]')]; expect(rules.map(r => r.getAttribute('data-rule'))).toEqual(['near_run', 'light', 'direction']); expect(rules[1].className).toContain('red'); expect(rules[1]).toHaveTextContent('below the horizon (dark)'); expect(within(rules[1] as HTMLElement).getByLabelText('rules it out')).toBeInTheDocument(); expect(within(rules[0] as HTMLElement).getByLabelText('fine')).toBeInTheDocument(); expect(within(rules[2] as HTMLElement).getByLabelText('not known')).toBeInTheDocument()
    expect(within(await screen.findByRole('region', { name: 'Panoramax near the point' })).getByText('Nothing within 500 m.')).toBeInTheDocument(); expect(within(screen.getByRole('region', { name: 'Google near the point' })).getByText('no GOOGLE_MAPS_API_KEY in secrets.env')).toBeInTheDocument(); expect(panel).toHaveTextContent('Filmed Thu 7 Mar 2024')
  })

  it('says when nothing rules a picture out, and can be closed', async () => {
    server.use(http.get('/api/streetview/near', () => HttpResponse.json({ cached: true, result: makeNearResult({ providers: { mapillary: { items: [makeNearItem({ usable: true, ruled_out: [], section: 'M31' })], radius_m: 100 }, panoramax: { items: [], radius_m: 100 }, google: { items: [], radius_m: 110 } } }), job: null })))
    const { user } = await click(); expect(await screen.findByText('Nothing rules it out')).toBeInTheDocument(); expect(screen.getByText('Already a candidate: section M31')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Make this a candidate' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Close' })); expect(screen.queryByLabelText('Nearest street view to the clicked point')).toBeNull()
  })

  it('shows a search button when nothing is cached, and the log while it searches, then the result', async () => {
    let polls = 0; const posts = recordRequests('/api/streetview/near')
    server.use(http.get('/api/streetview/near', ({ request }) => {
      const u = new URL(request.url); const lat = Number(u.searchParams.get('lat')), lon = Number(u.searchParams.get('lon')); polls++
      if (!posts.some(r => r.method === 'POST')) return HttpResponse.json({ cached: false, result: null, job: null })
      return polls < 4 ? HttpResponse.json({ cached: false, result: null, job: { lat, lon, running: true, log: ['asking mapillary…'], error: '' } }) : HttpResponse.json({ cached: true, result: makeNearResult(), job: null })
    }), http.post('/api/streetview/near', () => HttpResponse.json({ started: true })))
    const { user } = await click(); expect(await screen.findByRole('button', { name: 'Search for street view here' })).toBeInTheDocument(); expect(screen.queryByRole('region', { name: 'Mapillary near the point' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Search for street view here' })); expect(await screen.findByRole('status')).toHaveTextContent('Searching…'); expect(await screen.findByText('asking mapillary…')).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Mapillary near the point' }, { timeout: 5000 })).toBeInTheDocument(); expect(screen.queryByRole('status')).toBeNull()
    expect(posts.filter(r => r.method === 'POST')[0].body).toMatchObject({ folder: '/data', n: 5 })
  })

  it('puts the nearest street view under the map and shows a picture larger when it is clicked', async () => {
    server.use(http.get('/api/streetview/near', () => HttpResponse.json({ cached: true, result: makeNearResult(), job: null })))
    const { user } = await click(); const panel = await screen.findByLabelText('Nearest street view to the clicked point'); const map = screen.getByRole('application')
    expect(map.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user.click(await screen.findByRole('button', { name: 'Show Mapillary m9 larger' })); const big = screen.getByRole('dialog', { name: 'Larger picture' }); expect(within(big).getByRole('img').getAttribute('src')).toContain('id=m9&w=1024')
    await user.keyboard('{Escape}'); expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows the failure to ask', async () => {
    server.use(http.get('/api/streetview/near', () => HttpResponse.json({ detail: 'boom' }, { status: 500 }))); await click(); expect(await screen.findByRole('alert')).toHaveTextContent(/500|boom/)
  })
})

describe('how far a section is from the existing footage', () => {
  const near = (o: Partial<NonNullable<ReturnType<typeof makeSvSection>['near']>> = {}) => ({ before: { label: '0021', seconds: 240, km: 3.2 }, after: { label: '0023', seconds: 120, km: 1.1 }, overlaps: [], in_gap: 'G12', ...o })

  it('writes the nearest clip each way with the distance along the run and the time, or the clips it overlaps', () => {
    expect(nearText(near())).toBe('0021 3.2 km / 4 min before · 0023 1.1 km / 2 min after'); expect(nearText(near({ before: null }))).toBe('0023 1.1 km / 2 min after'); expect(nearText(near({ before: null, after: null }))).toBe('no footage near')
    expect(nearText(near({ overlaps: ['0022', '0023'] }))).toBe('Overlaps clip 0022, 0023'); expect(nearText(null)).toBe('')
  })

  it('shows it on the candidate, with the gap it fills, and as a column of the table', async () => {
    const sv = makeStreetView(); sv.sections[0].near = near(); serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const card = (await screen.findByLabelText('Sections that could be used')).querySelector('[data-section="M1"] [data-near]')!; expect(card).toHaveTextContent('Fills gap G12. Nearest footage: 0021 3.2 km / 4 min before · 0023 1.1 km / 2 min after')
    expect(screen.getByText('Nearest footage')).toBeInTheDocument(); expect(screen.getAllByRole('row')[1]).toHaveTextContent('G12: 0021 3.2 km / 4 min before · 0023 1.1 km / 2 min after')
  })

  it('says so, in amber, when a section overlaps footage', async () => {
    const sv = makeStreetView(); sv.sections[0].near = near({ overlaps: ['0022'], in_gap: null }); serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />)
    const card = (await screen.findByLabelText('Sections that could be used')).querySelector('[data-section="M1"] [data-near]')!; expect(card).toHaveTextContent('Nearest footage: Overlaps clip 0022'); expect(card.className).toContain('amber'); expect(card).not.toHaveTextContent('Fills gap')
  })

  it('filters the sections that overlap a clip away, so only those filling a gap remain', async () => {
    const sv = makeStreetView(); sv.sections = [makeSvSection({ id: 'M1', key: 'a', km0: 1, near: near() }), makeSvSection({ id: 'M2', key: 'b', km0: 2, near: near({ overlaps: ['0022'], in_gap: null }) }), makeSvSection({ id: 'M3', key: 'c', km0: 3, near: null })]; serve(sv)
    const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row'); const ids = () => [...document.querySelectorAll('tbody tr')].map(r => r.querySelector('td button')?.textContent?.replace('Mapillary ', ''))
    await user.click(screen.getByRole('button', { name: /Filters/ })); await user.click(screen.getByLabelText('Overlaps a camera clip')); expect(ids()).toEqual(['M1', 'M3'])
    await user.click(screen.getByLabelText('Overlaps a camera clip')); await user.click(screen.getByLabelText('In a gap (fills a gap in the footage)')); expect(ids()).toEqual(['M2'])
    expect(passes(makeSvSection({ near: near({ overlaps: ['1'] }) }), { ...DEFAULT_FILTERS, 'p:clip': false })).toBe(false)
  })
})

describe('the preview video of a section', () => {
  const pick = async (sv = makeStreetView()) => { serve(sv); const r = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await r.user.click((await screen.findAllByRole('row'))[1]); return r }

  it('offers to make it when it is not there, and starts it in the background', async () => {
    const seen = recordRequests('/api/streetview/video'); server.use(http.post('/api/streetview/video', () => HttpResponse.json({ started: true })))
    const { user } = await pick(); await user.click(await screen.findByRole('button', { name: 'Make a preview video' })); expect(screen.getByText(/about 12 s long, made in the background and kept/)).toBeInTheDocument()
    await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen.find(r => r.method === 'POST')!.body).toEqual({ folder: '/data', key: 'mapillary:s1:1.20' })
  })

  it('shows that it is being made, with the last line of its log', async () => {
    server.use(http.get('/api/streetview/video', () => HttpResponse.json({ exists: false, running: true, log: ['fetching', 'M1: 90 frames'], error: '', seconds: 12 }))); await pick()
    expect(await screen.findByRole('status')).toHaveTextContent('Making the video… M1: 90 frames'); expect(screen.queryByRole('button', { name: 'Make a preview video' })).toBeNull()
  })

  it('plays it when it exists', async () => {
    server.use(http.get('/api/streetview/video', () => HttpResponse.json({ exists: true, running: false, log: [], error: '', seconds: 12 }))); await pick()
    const v = await screen.findByLabelText('Preview video of this section'); expect(v.tagName).toBe('VIDEO'); expect(v.getAttribute('src')).toBe('/api/streetview/video/file?folder=%2Fdata&key=mapillary%3As1%3A1.20'); expect(screen.queryByRole('button', { name: 'Make a preview video' })).toBeNull()
  })

  it('shows why the last try failed and offers to try again; and refuses a second at once', async () => {
    server.use(http.get('/api/streetview/video', () => HttpResponse.json({ exists: false, running: false, log: [], error: 'streetview-video: mapillary answered 500', seconds: 12 }))); const { user } = await pick()
    expect(await screen.findByRole('alert')).toHaveTextContent('answered 500'); server.use(http.post('/api/streetview/video', () => HttpResponse.json({ started: false, reason: 'another preview video is being made' })))
    await user.click(screen.getByRole('button', { name: 'Make a preview video' })); await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('another preview video is being made'))
  })

  it('lets any section be used from its details, even one that is not a candidate', async () => {
    const sv = makeStreetView(); sv.sections[0] = makeSvSection({ plausible: false, why_not: 'only 12 pictures (needs 30)' }); await pick(sv)
    const seen = recordRequests('/api/streetview/choice'); server.use(http.post('/api/streetview/choice', () => HttpResponse.json({ key: sv.sections[0].key, choice: 'possible' })))
    const group = await screen.findByRole('group', { name: /in the film \(details\)/ }); expect(within(group).getByText(/Not a candidate \(only 12 pictures/)).toBeInTheDocument()
    await within(group).getByLabelText('Possible').click(); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen[0].body).toMatchObject({ choice: 'possible' })
  })

  it('offers a 360 video to look around in for a 360 section, made once, and played in the 360 viewer', async () => {
    const sv = makeStreetView(); sv.sections[0] = makeSvSection({ kind: '360', angles: null }); await pick(sv)
    const seen = recordRequests('/api/streetview/video'); let made = false
    server.use(http.get('/api/streetview/video', ({ request }) => HttpResponse.json({ exists: made && new URL(request.url).searchParams.get('pano') === 'true', running: false, log: [], error: '', seconds: 12 })), http.post('/api/streetview/video', () => { made = true; return HttpResponse.json({ started: true }) }))
    const { user } = { user: (await import('@testing-library/user-event')).default.setup() }
    await user.click(await screen.findByRole('button', { name: 'Make a 360° video to look around in' })); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen.filter(r => r.method === 'POST')[0].body).toMatchObject({ pano: true })
    expect(await screen.findByLabelText(/: look around$/)).toBeInTheDocument()
  })

  it('offers no look-around for Google, which only gives the view along the road', async () => {
    const sv = makeStreetView(); sv.sections[0] = makeSvSection({ id: 'G1', key: 'google:g:1.20', provider: 'google', kind: '360', angles: null }); await pick(sv); await screen.findByRole('button', { name: 'Make a preview video' }); expect(screen.queryByRole('button', { name: 'Make a 360° video to look around in' })).toBeNull()
  })

  it('offers no 360 video for a flat camera', async () => {
    const sv = makeStreetView(); sv.sections[0] = makeSvSection({ kind: '2d' }); await pick(sv); await screen.findByRole('button', { name: 'Make a preview video' }); expect(screen.queryByRole('button', { name: 'Make a 360° video to look around in' })).toBeNull()
  })

  it('offers a video for Google like the others', async () => {
    const sv = makeStreetView(); sv.sections[0] = makeSvSection({ id: 'G1', key: 'google:g:1.20', provider: 'google', kind: '360', angles: null }); await pick(sv)
    expect(await screen.findByRole('button', { name: 'Make a preview video' })).toBeEnabled()
  })

  it('marks a candidate whose preview video is ready', async () => {
    const sv = makeStreetView(); sv.sections[0].has_video = true; serve(sv); setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); expect(await screen.findByText('preview video ready')).toBeInTheDocument()
  })
})

describe('the Street view link', () => {
  it('is under Overview and opens the page', async () => {
    serve(); const { user } = setup(<Workspace folder="/data" onChange={() => {}} />)
    const btn = await screen.findByRole('button', { name: 'Street view' }); const overview = screen.getByRole('button', { name: 'Overview' }); expect(overview.nextElementSibling).toBe(btn)
    await user.click(btn); expect(await screen.findByRole('region', { name: 'Street view' })).toBeInTheDocument(); expect(within(screen.getByRole('region', { name: 'Street view' })).getByText('Road parts of the run')).toBeInTheDocument()
  })
})

describe('what is shown to start with, and making a nearby capture a candidate', () => {
  it('shows only sections that could be used until more are asked for', async () => {
    const sv = makeStreetView(); sv.sections = [makeSvSection({ id: 'M1', key: 'a', plausible: true }), makeSvSection({ id: 'M2', key: 'b', plausible: false, why_not: 'only 3 pictures' })]; serve(sv)
    const { user } = setup(<StreetViewPage folder="/data" />); await screen.findAllByRole('row')
    expect(screen.getByText('1 of 2 sections shown')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Filters/ })); await user.click(screen.getByText('Show everything')); expect(screen.getByText('2 of 2 sections shown')).toBeInTheDocument()
    await user.click(screen.getByText('Usable only')); expect(screen.getByText('1 of 2 sections shown')).toBeInTheDocument()
  })

  it('makes a nearby capture a candidate with a button, once', async () => {
    server.use(http.get('/api/streetview/near', () => HttpResponse.json({ cached: true, result: makeNearResult({ providers: { mapillary: { items: [makeNearItem({ section: null })], radius_m: 100 }, panoramax: { items: [], radius_m: 100 }, google: { items: [], radius_m: 110 } } }), job: null })))
    const seen = recordRequests('/api/streetview/promote'); server.use(http.post('/api/streetview/promote', () => HttpResponse.json({ key: 'mapillary:s:1.00', id: 'M+1' })))
    serve(); const { user } = setup(<StreetViewPage folder="/data" initialFilters={SHOW_ALL} />); await screen.findAllByRole('row')
    fireEvent.click(await screen.findByRole('application'), { clientX: 40, clientY: 30 })
    await user.click(await screen.findByRole('button', { name: 'Make this a candidate' }))
    await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen[0].body).toMatchObject({ folder: '/data', provider: 'mapillary', id: 'm9' })
    expect(await screen.findByText('Already a candidate: section M+1')).toBeInTheDocument()
  })
})
