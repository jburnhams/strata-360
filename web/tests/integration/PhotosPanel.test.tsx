import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import PhotosPanel from '../../src/components/PhotosPanel'
import PhotoStrip from '../../src/components/PhotoStrip'
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
    expect(screen.getByRole('alert', { name: '' })).toHaveTextContent('6.2 km apart'); expect(document.querySelector('[data-photo="p3"]')).toHaveTextContent('(run track)'); expect(document.querySelector('[data-photo="p3"]')).toHaveTextContent('between clips')
  })

  it('opens the clip or gap a photo falls in', async () => {
    const open = vi.fn(); const { user } = setup(<PhotosPanel folder="/data" photos={[makePhoto(), makePhoto({ id: 'p2', where: { kind: 'gap', id: 'G03' } })]} tz="Europe/Brussels" onChanged={() => {}} onOpen={open} />)
    await user.click(screen.getByRole('button', { name: 'clip 0023' })); expect(open).toHaveBeenCalledWith({ kind: 'clip', id: 'CAM_20260222190000_0023_D' })
    await user.click(screen.getByRole('button', { name: 'gap G03' })); expect(open).toHaveBeenCalledWith({ kind: 'gap', id: 'G03' })
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

describe('PhotoStrip', () => {
  const photos = [makePhoto(), makePhoto({ id: 'p2', where: { kind: 'gap', id: 'G03' } }), makePhoto({ id: 'p3', where: null })]
  it('shows only the photos whose time falls in the clip or gap', () => {
    const { rerender } = setup(<PhotoStrip folder="/data" photos={photos} tz="UTC" kind="clip" id="CAM_20260222190000_0023_D" />)
    expect(screen.getByText(/Photos taken during this clip/)).toBeInTheDocument(); expect(document.querySelectorAll('[data-photo]')).toHaveLength(1)
    rerender(<PhotoStrip folder="/data" photos={photos} tz="UTC" kind="gap" id="G03" />); expect(screen.getByText(/Photos taken in this gap/)).toBeInTheDocument(); expect(document.querySelector('[data-photo="p2"]')).not.toBeNull()
  })
  it('shows nothing when there are none', () => {
    const { container } = setup(<PhotoStrip folder="/data" photos={photos} tz="UTC" kind="clip" id="CAM_X" />); expect(container).toBeEmptyDOMElement()
  })
})
