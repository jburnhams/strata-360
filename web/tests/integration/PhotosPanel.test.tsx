import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import PhotosPanel from '../../src/components/PhotosPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makePhoto } from '../utils/factories'
import { recordRequests } from '../utils/api'
import { server } from '../utils/server'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('PhotosPanel', () => {
  it('invites you to add photos when there are none', () => {
    setup(<PhotosPanel folder="/data" photos={[]} tz="Europe/Brussels" onChanged={() => {}} onOpen={() => {}} />)
    expect(screen.getByText(/No photos yet/)).toBeInTheDocument(); expect(screen.getByText('Add photos')).toBeInTheDocument()
  })

  it('shows each photo with when it was taken, how far into the race, where, and a warning when its position and the run disagree', () => {
    const photos = [makePhoto(), makePhoto({ id: 'p2', name: 'IMG_2.jpg', flag: "the photo's position and the run's at that time are 6.2 km apart (the camera clock may be wrong)", apart_m: 6200, where: { kind: 'gap', id: 'G03' } }), makePhoto({ id: 'p3', name: 'IMG_3.jpg', where: null, loc: { lat: 50.2, lon: 5.2, source: 'run track' }, gps: null, apart_m: null })]
    setup(<PhotosPanel folder="/data" photos={photos} tz="Europe/Brussels" onChanged={() => {}} onOpen={() => {}} />)
    expect(screen.getByText('Photos')).toBeInTheDocument(); expect(screen.getByText(/\(3, 1 to check\)/)).toBeInTheDocument()
    const first = document.querySelector('[data-photo="p1"]')!; expect(first).toHaveTextContent('Sat 21 Feb 19:53:20'); expect(first).toHaveTextContent('1:12:05 into the race · km 12.1 · gps clock'); expect(first).toHaveTextContent('50.1000, 5.1000 (photo gps) · 25 m from the run')
    expect(first.querySelector('img')!.getAttribute('src')).toContain('/api/photos/thumb?'); expect(first.querySelector('a')!.getAttribute('href')).toContain('/api/photos/file?')
    expect(screen.getByRole('alert', { name: '' })).toHaveTextContent('6.2 km apart'); expect(document.querySelector('[data-photo="p3"]')).toHaveTextContent('(run track)');
  })

  it('offers to open only the photos ticked for the film (they are in the film list)', async () => {
    const open = vi.fn(); const { user } = setup(<PhotosPanel folder="/data" photos={[makePhoto(), makePhoto({ id: 'p2', must: true })]} tz="Europe/Brussels" onChanged={() => {}} onOpen={open} />)
    expect(screen.getAllByRole('button', { name: 'Open in the film list' })).toHaveLength(1); await user.click(screen.getByRole('button', { name: 'Open in the film list' })); expect(open).toHaveBeenCalledWith(expect.objectContaining({ id: 'p2' }))
  })

  it('adds several photos one after the other, lists the ones refused, and asks for the list again', async () => {
    const seen = recordRequests('/api/photos'); const changed = vi.fn()
    server.use(http.post('/api/photos', ({ request }) => new URL(request.url).searchParams.get('filename') === 'bad.png' ? HttpResponse.json({ detail: 'bad.png: not an image I can read' }, { status: 400 }) : HttpResponse.json(makePhoto())))
    const { user } = setup(<PhotosPanel folder="/data" photos={[]} tz="Europe/Brussels" onChanged={changed} onOpen={() => {}} />)
    await user.upload(screen.getByLabelText('Add photos'), [new File(['a'], 'a.jpg', { type: 'image/jpeg' }), new File(['b'], 'bad.png', { type: 'image/png' }), new File(['c'], 'c.heic', { type: 'image/heic' })])
    expect(await screen.findByRole('alert')).toHaveTextContent('bad.png: not an image I can read')
    expect(seen.filter(r => r.method === 'POST').map(r => r.url.searchParams.get('filename'))).toEqual(['a.jpg', 'bad.png', 'c.heic']); await waitFor(() => expect(changed).toHaveBeenCalled())
  })

  it('removes a photo', async () => {
    const seen = recordRequests('/api/photos'); const changed = vi.fn(); server.use(http.delete('/api/photos', () => HttpResponse.json({ photos: [] })))
    const { user } = setup(<PhotosPanel folder="/data" photos={[makePhoto()]} tz="Europe/Brussels" onChanged={changed} onOpen={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'Remove IMG_0001.jpg' })); await waitFor(() => expect(changed).toHaveBeenCalled()); expect(seen.some(r => r.method === 'DELETE' && r.url.searchParams.get('id') === 'p1')).toBe(true)
  })
})

describe('PhotosPanel analysis', () => {
  const analysed = makePhoto({ analysis: { stages: ['scenes', 'places'], setting: 'trail', weather: 'cloud', description: 'A muddy path through trees.', scenery: 7, clarity: 4, tags: ['trees', 'mud'], objects: [{ label: 'bottle', n: 2 }, { label: 'bicycle', n: 1 }], place: 'Nadrin (Luxembourg)', people: 2, me: true, face_clear: true, exposure: 'dark', quality: 'ok', overlay: true } })

  it('shows what the analysis found on each photo', () => {
    setup(<PhotosPanel folder="/data" photos={[analysed, makePhoto({ id: 'p2', name: 'IMG_2.jpg', analysis: { stages: [] } })]} tz="UTC" onChanged={() => {}} onOpen={() => {}} />)
    const a = document.querySelector('[data-photo="p1"] [data-analysis]')!; expect(a).toHaveTextContent('A muddy path through trees.'); expect(a).toHaveTextContent('Nadrin (Luxembourg) · trail, cloud · scenery 7/10, clarity 4/5 · 2 people, you among them (face clear) · objects: 2 bottle, bicycle · looks dark')
    expect(a).toHaveTextContent('treesmud'); expect(a.querySelector('a')!.getAttribute('href')).toContain('overlay=1'); expect(document.querySelector('[data-photo="p2"] [data-analysis]')).toBeNull()
  })

  it('starts the analysis, shows its progress, and says why it stopped', async () => {
    const seen = recordRequests('/api/photos/analyse'); server.use(http.post('/api/photos/analyse', () => HttpResponse.json({ started: true }))); const changed = vi.fn()
    const { user, rerender } = setup(<PhotosPanel folder="/data" photos={[makePhoto()]} tz="UTC" onChanged={changed} onOpen={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'Analyse photos' })); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ folder: '/data', force: false })); expect(changed).toHaveBeenCalled()
    rerender(<PhotosPanel folder="/data" photos={[makePhoto()]} tz="UTC" job={{ running: true, log: ['places: 1 photo(s)', 'people: 1 photo(s)'], error: '' }} onChanged={changed} onOpen={() => {}} />)
    expect(screen.getByText('people: 1 photo(s)')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Analysing…' })).toBeDisabled()
    rerender(<PhotosPanel folder="/data" photos={[makePhoto()]} tz="UTC" job={{ running: false, log: [], error: 'identity: RuntimeError: no wearer profile profiles/me.npz' }} onChanged={changed} onOpen={() => {}} />)
    expect(screen.getByRole('alert')).toHaveTextContent('The analysis stopped: identity: RuntimeError: no wearer profile')
  })

  it('offers to redo everything once the photos have been analysed', async () => {
    const seen = recordRequests('/api/photos/analyse'); server.use(http.post('/api/photos/analyse', () => HttpResponse.json({ started: true })))
    const { user } = setup(<PhotosPanel folder="/data" photos={[analysed]} tz="UTC" onChanged={() => {}} onOpen={() => {}} />)
    expect(screen.getByRole('button', { name: 'Analyse again' })).toBeInTheDocument(); await user.click(screen.getByRole('button', { name: 'Redo all' })); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ force: true }))
  })
})

describe('Use in the film', () => {
  it('marks a photo to be used in the film, and shows it ticked once it is', async () => {
    const seen = recordRequests('/api/photos/settings'); server.use(http.post('/api/photos/settings', () => HttpResponse.json({ id: 'p1', must: true }))); const changed = vi.fn()
    const { user, rerender } = setup(<PhotosPanel folder="/data" photos={[makePhoto()]} tz="UTC" onChanged={changed} onOpen={() => {}} />)
    const box = screen.getByRole('checkbox', { name: 'Use IMG_0001.jpg in the film' }); expect(box).not.toBeChecked(); await user.click(box)
    await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ folder: '/data', id: 'p1', must: true })); await waitFor(() => expect(changed).toHaveBeenCalled())
    rerender(<PhotosPanel folder="/data" photos={[makePhoto({ must: true })]} tz="UTC" onChanged={changed} onOpen={() => {}} />); expect(screen.getByRole('checkbox', { name: 'Use IMG_0001.jpg in the film' })).toBeChecked()
  })
})
