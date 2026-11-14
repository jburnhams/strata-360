import { beforeAll, describe, expect, it, vi } from 'vitest'
import { installLayoutShims } from 'strata-react/testing'
import TrackCharts from '../../src/components/TrackCharts'
import { screen, setup, within } from '../utils/render'
import { makeTrackClip, makeTrackSeries } from '../utils/factories'

const base = { series: makeTrackSeries(), clips: [makeTrackClip(), makeTrackClip({ id: 'CAM_20260222210000_0024_D', label: '0024', t_mid: 20000, used: false, used_s: 0 }), makeTrackClip({ id: 'CAM_20260221170000_0001_D', label: '0001', covered: false, t_mid: undefined })],
  xMode: 'time' as const, tz: 'Europe/Brussels', cursor: null as number | null, onCursor: vi.fn(), onOpenClip: vi.fn() }
beforeAll(() => { installLayoutShims() })                                                                    // the charts measure their box

describe('TrackCharts', () => {
  it('draws elevation and pace as two charts with a marker for every clip on the track and none for the others', () => {
    setup(<TrackCharts {...base} />)
    expect(screen.getByRole('img', { name: 'Elevation' })).toBeInTheDocument(); expect(screen.getByRole('img', { name: 'Pace' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Clip 0023/ })).toHaveLength(2); expect(screen.getAllByRole('button', { name: /^Clip 0024/ })).toHaveLength(2); expect(screen.queryByRole('button', { name: /^Clip 0001/ })).not.toBeInTheDocument()
  })

  it('opens a clip when its marker is clicked or Enter is pressed, and shows the clip\'s card on focus', async () => {
    const open = vi.fn(); const { user } = setup(<TrackCharts {...base} onOpenClip={open} renderClipCard={c => <span>card for {c.label}</span>} />)
    const m = screen.getAllByRole('button', { name: /^Clip 0024/ })[1]
    await user.keyboard('{Tab}'); m.focus(); expect(await screen.findByRole('tooltip')).toHaveTextContent('card for 0024')
    await user.click(m); expect(open).toHaveBeenCalledWith('CAM_20260222210000_0024_D')
    m.focus(); await user.keyboard('{Enter}'); expect(open).toHaveBeenCalledTimes(2)
  })

  it('moves the cursor with the keyboard on a chart, as a time the map can show, and clears it when the focus leaves', async () => {
    const cur = vi.fn(); const { user } = setup(<TrackCharts {...base} onCursor={cur} />)
    screen.getAllByRole('slider', { name: /Elevation: read values/ })[0].focus(); await user.keyboard('{ArrowLeft}')
    expect(cur.mock.calls.some(c => typeof c[0] === 'number')).toBe(true)
  })

  it('shows the map\'s cursor on the charts', () => {
    const { rerender } = setup(<TrackCharts {...base} />); const before = screen.getByRole('img', { name: 'Elevation' }).innerHTML
    rerender(<TrackCharts {...base} cursor={900 * 5} />); expect(screen.getByRole('img', { name: 'Elevation' }).innerHTML).not.toBe(before)
  })

  it('names the stretch where the runner stood still, on both charts', () => {
    setup(<TrackCharts {...base} />); expect(screen.getAllByText('Stopped')).toHaveLength(2)
  })

  it('draws the lowest and highest elevation of each stretch, and pace in min/km', () => {
    setup(<TrackCharts {...base} />)
    expect(screen.getAllByText('Lowest to highest in each stretch').length).toBeGreaterThan(0); expect(within(screen.getByRole('table', { name: 'Pace' })).getAllByText(/^\d+:\d\d \/km$/).length).toBeGreaterThan(2)
    expect(within(screen.getByRole('table', { name: 'Pace' })).getAllByText(/^(Sun|Mon|Sat) \d\d:\d\d$/).length).toBeGreaterThan(2)             // the time axis is clock time
  })

  it('switches the horizontal axis to distance', () => {
    const { rerender } = setup(<TrackCharts {...base} />); rerender(<TrackCharts {...base} xMode="km" />)
    expect(within(screen.getByRole('table', { name: 'Elevation' })).getByRole('columnheader', { name: 'Distance' })).toBeInTheDocument(); expect(within(screen.getByRole('table', { name: 'Elevation' })).getAllByText(/^\d+(\.\d)? km$/).length).toBeGreaterThan(2)
  })

  it('has no accessibility violations', async () => {
    const { axe } = await import('vitest-axe'); const { container } = setup(<TrackCharts {...base} />); expect(await axe(container)).toHaveNoViolations()
  })
})
