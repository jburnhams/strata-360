import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent } from '@testing-library/react'
import TrackMap from '../../src/components/TrackMap'
import { screen, setup } from '../utils/render'
import { stubLayout } from '../utils/media'
import { makeTrackClip, makeTrackLine } from '../utils/factories'

let unstub = () => {}
beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); unstub = stubLayout() })
afterEach(() => { unstub(); vi.useRealTimers() })

const props = () => ({ base: makeTrackLine(), clips: [makeTrackClip(), makeTrackClip({ id: 'CAM_B', label: '0024', used: false, lat: 50.15, lon: 5.2 }), makeTrackClip({ id: 'CAM_C', label: '0001', covered: false, lat: undefined, lon: undefined })],
  cursor: null as number | null, onCursor: vi.fn(), onHoverClip: vi.fn(), onOpenClip: vi.fn(), fetchDetail: vi.fn(async () => makeTrackLine()) })

describe('TrackMap', () => {
  it('draws the map with a marker for each clip on the track, labelled with its number, and none for a clip that is not on it', () => {
    setup(<TrackMap {...props()} />)
    expect(screen.getByRole('application', { name: 'Race map' })).toBeInTheDocument()
    expect(screen.getByTitle('Clip 0023')).toHaveTextContent('0023'); expect(screen.getByTitle('Clip 0024')).toHaveTextContent('0024'); expect(screen.queryByTitle('Clip 0001')).not.toBeInTheDocument()
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
    const p = props(); const { rerender, container } = setup(<TrackMap {...p} />); const paths = () => container.querySelectorAll('.leaflet-overlay-pane path').length; const before = paths()
    rerender(<TrackMap {...p} cursor={2000} />); expect(paths()).toBe(before + 1)
    rerender(<TrackMap {...p} cursor={null} />); expect(paths()).toBe(before)
  })

  it('draws nothing, and does not fail, for a track with no points', () => {
    setup(<TrackMap {...props()} base={{ lat: [], lon: [], t: [] }} clips={[]} />)
    expect(screen.getByRole('application', { name: 'Race map' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Zoom in' })).not.toBeInTheDocument()
  })
})
