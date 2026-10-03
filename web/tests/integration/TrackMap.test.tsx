import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent } from '@testing-library/react'
import L from 'leaflet'
import TrackMap from '../../src/components/TrackMap'
import { screen, setup } from '../utils/render'
import { makePhoto, makeTrackClip, makeTrackLine } from '../utils/factories'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers() })

const props = () => ({ base: makeTrackLine(), clips: [makeTrackClip(), makeTrackClip({ id: 'CAM_B', label: '0024', used: false, lat: 50.15, lon: 5.2 }), makeTrackClip({ id: 'CAM_C', label: '0001', covered: false, lat: undefined, lon: undefined })],
  cursor: null as number | null, onCursor: vi.fn(), onHoverClip: vi.fn(), onOpenClip: vi.fn(), fetchDetail: vi.fn(async () => makeTrackLine()) })

describe('TrackMap', () => {
  it('puts the server\'s map tiles behind the track when there is a background, and none otherwise', () => {
    const { container, rerender } = setup(<TrackMap {...props()} />)
    expect(container.querySelector('.leaflet-tile-pane .leaflet-layer')).toBeNull()
    rerender(<TrackMap {...props()} background={{ url: '/api/tiles/tf-landscape/{z}/{x}/{y}', tilePx: 512 }} />)
    expect(container.querySelector('.leaflet-tile-pane .leaflet-layer')).not.toBeNull()
    rerender(<TrackMap {...props()} />); expect(container.querySelector('.leaflet-tile-pane .leaflet-layer')).toBeNull()
  })

  it('draws the map with a marker for each clip on the track, labelled with its number, and none for a clip that is not on it', () => {
    setup(<TrackMap {...props()} />)
    expect(screen.getByRole('application', { name: 'Race map' })).toBeInTheDocument()
    expect(screen.getByTitle('Clip 0023')).toHaveTextContent('0023'); expect(screen.getByTitle('Clip 0024')).toHaveTextContent('0024'); expect(screen.queryByTitle('Clip 0001')).not.toBeInTheDocument()
  })

  it('draws routes dashed and runs plain under the race track, and a marker with a tooltip for each point of interest', () => {
    const lines = vi.spyOn(L, 'polyline')
    setup(<TrackMap {...props()} extras={[{ id: 't2', kind: 'route', name: 'course.gpx', lat: [50, 50.1], lon: [5, 5.1] }, { id: 't3', kind: 'run', name: 'watch.fit', lat: [50, 50.2], lon: [5, 5.2] }]} pois={[{ name: 'Aid 1', lat: 50.05, lon: 5.05, ele: 120, sym: '', desc: 'water', track: 't2' }]} />)
    const opts = lines.mock.calls.map(c => c[1] as L.PolylineOptions)
    expect(opts.some(o => o.color === '#2563eb' && o.dashArray)).toBe(true); expect(opts.some(o => o.color === '#a3a3a3' && !o.dashArray)).toBe(true)
    expect(screen.getByTitle('Aid 1')).toBeInTheDocument(); lines.mockRestore()
  })

  it('marks each place the run leaves the route with a red stretch and an exclamation mark', () => {
    const lines = vi.spyOn(L, 'polyline')
    const { container } = setup(<TrackMap {...props()} divergences={[{ lat: 50.05, lon: 5.05, peak_m: 348, length_m: 660, km: 72, t: 0, line: [[50.04, 5.04], [50.06, 5.06]] }]} />)
    expect(screen.getByTitle('348 m off the route')).toHaveTextContent('!'); expect(container.querySelector('[data-divergence]')).not.toBeNull()
    expect(lines.mock.calls.some(c => (c[1] as L.PolylineOptions).color === '#dc2626')).toBe(true); lines.mockRestore()
  })

  it('draws the highlighted tracks bold yellow with a black outline, and tells the list when a route is pointed at or clicked', () => {
    const lines = vi.spyOn(L, 'polyline'); const hover = vi.fn(), toggle = vi.fn()
    setup(<TrackMap {...props()} onHoverTrack={hover} onToggleTrack={toggle} extras={[{ id: 't2', kind: 'route', name: 'course.gpx', lat: [50, 50.1], lon: [5, 5.1] }]} highlight={[{ id: 't2', kind: 'route', name: 'course.gpx', lat: [50, 50.1], lon: [5, 5.1] }]} />)
    const opts = lines.mock.calls.map(c => c[1] as L.PolylineOptions); expect(opts.some(o => o.color === '#facc15' && o.weight === 5)).toBe(true); expect(opts.some(o => o.color === '#000' && o.weight === 9)).toBe(true)
    const route = lines.mock.results.map(r => r.value as L.Polyline).find((_, i) => (opts[i] as L.PolylineOptions).color === '#2563eb')!
    route.fire('mouseover'); route.fire('mouseout'); route.fire('click'); expect(hover.mock.calls).toEqual([['t2'], [null]]); expect(toggle).toHaveBeenCalledWith('t2'); lines.mockRestore()
  })

  it('marks the start in green, the finish line from the route and where the run ended in red', () => {
    const { container } = setup(<TrackMap {...props()} tz="UTC" ends={{ start: { lat: 50, lon: 5, t: 1_771_700_000 }, end: { lat: 50.1, lon: 5.2, t: 1_771_800_000, km: 379.4, elapsed_s: 100000 }, finish: { lat: 50.12, lon: 5.22 } }} />)
    for (const k of ['start', 'finish', 'end']) expect(container.querySelector(`[data-end="${k}"]`)).not.toBeNull()
    expect(screen.getByTitle('Start')).toBeInTheDocument(); expect(screen.getByTitle('Finish line')).toBeInTheDocument(); expect(screen.getByTitle('End of the run')).toBeInTheDocument()
  })

  it('rings the finish line, and only that, when the finish is highlighted', () => {
    const ends = { start: { lat: 50, lon: 5, t: 0 }, end: { lat: 50.1, lon: 5.2, t: 10, km: 1, elapsed_s: 10 }, finish: { lat: 50.12, lon: 5.22 } }
    const { container, rerender } = setup(<TrackMap {...props()} ends={ends} />); expect(container.querySelector('[data-end-hl]')).toBeNull()
    rerender(<TrackMap {...props()} ends={ends} ringEnds />); const hl = container.querySelectorAll('[data-end-hl]'); expect(hl).toHaveLength(1); expect(hl[0].getAttribute('data-end')).toBe('finish')
  })

  it('has no finish line without a route', () => {
    const { container } = setup(<TrackMap {...props()} ends={{ start: { lat: 50, lon: 5, t: 0 }, end: { lat: 50.1, lon: 5.2, t: 10, km: 1, elapsed_s: 10 }, finish: null }} />)
    expect(container.querySelector('[data-end="finish"]')).toBeNull(); expect(container.querySelector('[data-end="end"]')).not.toBeNull()
  })

  it('puts a camera icon at each photo with a position, with its picture on hover, and opens it when clicked', async () => {
    const open = vi.fn(); const photos = [makePhoto(), makePhoto({ id: 'p2', name: 'IMG_2.jpg', loc: null }), makePhoto({ id: 'p3', name: 'IMG_3.jpg', flag: 'far apart', loc: { lat: 50.2, lon: 5.2, source: 'photo gps' } })]
    const { container, user } = setup(<TrackMap {...props()} photos={photos} photoThumb={id => `/thumb/${id}`} onOpenPhoto={open} />)
    expect(container.querySelectorAll('[data-photo-marker]')).toHaveLength(2)                                       // (the one with no position has no icon)
    await user.hover(screen.getByTitle('IMG_3.jpg')); const tip = await screen.findByText('IMG_3.jpg ⚠'); expect(tip.parentElement!.querySelector('img')!.getAttribute('src')).toBe('/thumb/p3')
    fireEvent.click(screen.getByTitle('IMG_3.jpg')); expect(open).toHaveBeenCalledWith(photos[2])
  })

  it('numbers the checkpoints between routes', () => {
    const { container } = setup(<TrackMap {...props()} pois={[{ name: 'Checkpoint 2', lat: 50.05, lon: 5.05, ele: null, sym: 'checkpoint', desc: 'a → b', track: 'checkpoint', n: 2 }]} />)
    expect(screen.getByTitle('Checkpoint 2')).toHaveTextContent('2'); expect(container.querySelector('[data-checkpoint]')).not.toBeNull()
  })

  it('shows how long the run stood still at a checkpoint when it is hovered', async () => {
    const t = 1_771_700_000
    const { user } = setup(<TrackMap {...props()} tz="UTC" pois={[{ name: 'Checkpoint 1', lat: 50.05, lon: 5.05, ele: null, sym: 'checkpoint', desc: 'a.gpx → b.gpx', track: 'checkpoint', n: 1, stop: { arrived: t + 300, left: t + 2400, stopped_s: 2100, radius_m: 300 } }, { name: 'Checkpoint 2', lat: 50.1, lon: 5.1, ele: null, sym: 'checkpoint', desc: '', track: 'checkpoint', n: 2, stop: { arrived: null, left: null, stopped_s: 0, radius_m: 300 } }]} />)
    await user.hover(screen.getByTitle('Checkpoint 1')); const tip = await screen.findByText(/Time here 35 min 00 s/); expect(tip).toHaveTextContent('(18:58 to 19:33)'); await user.unhover(screen.getByTitle('Checkpoint 1'))
    await user.hover(screen.getByTitle('Checkpoint 2')); expect(await screen.findByText('Did not slow down within 300 m')).toBeInTheDocument()
  })

  it('rings a highlighted checkpoint in bold yellow', () => {
    const cp = (n: number) => ({ name: `Checkpoint ${n}`, lat: 50.05 + n / 100, lon: 5.05, ele: null, sym: 'checkpoint', desc: '', track: 'checkpoint', n })
    const { container, rerender } = setup(<TrackMap {...props()} pois={[cp(1), cp(2)]} />)
    expect(container.querySelector('[data-checkpoint-hl]')).toBeNull()
    rerender(<TrackMap {...props()} pois={[cp(1), cp(2)]} highlightCheckpoints={[2]} />)
    const hl = container.querySelectorAll('[data-checkpoint-hl]'); expect(hl).toHaveLength(1); expect(hl[0]).toHaveTextContent('2'); expect(hl[0].getAttribute('style')).toContain('#facc15')
  })

  it('colours a marker green when the draft plays the clip and grey when it does not', () => {
    setup(<TrackMap {...props()} />)
    expect(screen.getByTitle('Clip 0023').innerHTML).toContain('#16a34a'); expect(screen.getByTitle('Clip 0024').innerHTML).toContain('#78716c')
  })

  it('reports hover for the card and opens the clip on a click', () => {
    const p = props(); setup(<TrackMap {...p} />); const m = screen.getByTitle('Clip 0023')
    fireEvent.mouseOver(m, { clientX: 120, clientY: 80 }); expect(p.onHoverClip).toHaveBeenCalledWith(expect.objectContaining({ label: '0023' }), 120, 80)
    fireEvent.mouseOut(m); expect(p.onHoverClip).toHaveBeenLastCalledWith(null)
    fireEvent.click(m); expect(p.onOpenClip).toHaveBeenCalledWith('CAM_20260222190000_0023_D')
  })

  it('has zoom buttons and a button that resets the view', () => {
    setup(<TrackMap {...props()} />)
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Zoom out' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Reset the view' })).toBeInTheDocument()
  })

  it('asks for the track in more detail for the part in view once zoomed in, and not before', async () => {
    const p = props(); const { user } = setup(<TrackMap {...p} />)
    await act(() => vi.advanceTimersByTimeAsync(400)); expect(p.fetchDetail).not.toHaveBeenCalled()             // the first view is the coarse line
    for (let i = 0; i < 3; i++) await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    await act(() => vi.advanceTimersByTimeAsync(400))
    expect(p.fetchDetail).toHaveBeenCalled(); const [la0, lo0, la1, lo1] = (p.fetchDetail.mock.calls.at(-1) as unknown as [number[]])[0]
    expect(la1).toBeGreaterThan(la0); expect(lo1).toBeGreaterThan(lo0); expect(la0).toBeGreaterThan(49.9); expect(la1).toBeLessThan(50.3)         // a box around the part of the race in view, not the whole race
  })

  it('shows the shared cursor as a dot on the track and removes it', () => {
    const p = props(); const { rerender, container } = setup(<TrackMap {...p} />); const dots = () => container.querySelectorAll('[data-cursor-dot]').length
    expect(dots()).toBe(0); rerender(<TrackMap {...p} cursor={2000} />); expect(dots()).toBe(1)
    rerender(<TrackMap {...p} cursor={4000} />); expect(dots()).toBe(1)                                              // moved, not added again
    rerender(<TrackMap {...p} cursor={null} />); expect(dots()).toBe(0)
  })

  it('draws nothing, and does not fail, for a track with no points', () => {
    setup(<TrackMap {...props()} base={{ lat: [], lon: [], t: [] }} clips={[]} />)
    expect(screen.getByRole('application', { name: 'Race map' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Zoom in' })).not.toBeInTheDocument()
  })

  it('moves markers that would sit on top of each other apart, and leaves a lone marker where it is', () => {
    const p = props(); p.clips = [makeTrackClip(), makeTrackClip({ id: 'CAM_B', label: '0024' }), makeTrackClip({ id: 'CAM_D', label: '0025' }), makeTrackClip({ id: 'CAM_E', label: '0030', lat: 50.19, lon: 5.285 })]   // three clips in one place, one far away
    setup(<TrackMap {...p} />)
    const offset = (t: string) => { const e = screen.getByTitle(t); return `${e.style.marginLeft}|${e.style.marginTop}` }
    expect(new Set([offset('Clip 0023'), offset('Clip 0024'), offset('Clip 0025')]).size).toBe(3); expect(offset('Clip 0030')).toBe(offset('Clip 0023').split('|')[0] + '|' + '-11px')
  })

  it('lets the wheel scroll the page until the map has been clicked, then zooms with it, and stops when the mouse leaves', () => {
    setup(<TrackMap {...props()} />)
    const c = screen.getByRole('application', { name: 'Race map' }); const wheel = () => { const e = new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -120 }); c.dispatchEvent(e); return e.defaultPrevented }
    expect(wheel()).toBe(false)                                                        // not intercepted: the page scrolls
    fireEvent.click(c); expect(wheel()).toBe(true)                                     // after a click the map takes the wheel
    fireEvent.mouseLeave(c); expect(wheel()).toBe(false)                               // and gives it back
  })
})
