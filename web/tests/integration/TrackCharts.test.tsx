import { describe, expect, it, vi } from 'vitest'
import { fireEvent } from '@testing-library/react'
import TrackCharts from '../../src/components/TrackCharts'
import { screen, setup, within } from '../utils/render'
import { stubRect } from '../utils/media'
import { makeTrackClip, makeTrackSeries } from '../utils/factories'

const base = { series: makeTrackSeries(), clips: [makeTrackClip(), makeTrackClip({ id: 'CAM_20260222210000_0024_D', label: '0024', t_mid: 20000, used: false, used_s: 0 }), makeTrackClip({ id: 'CAM_20260221170000_0001_D', label: '0001', covered: false, t_mid: undefined })],
  xMode: 'time' as const, tz: 'Europe/Brussels', cursor: null as number | null, onCursor: vi.fn(), onHoverClip: vi.fn(), onOpenClip: vi.fn() }

describe('TrackCharts', () => {
  it('draws elevation and pace as two charts with a marker for every clip on the track and none for the others', () => {
    setup(<TrackCharts {...base} />)
    const e = screen.getByRole('group', { name: 'Elevation chart' }), p = screen.getByRole('group', { name: 'Pace chart' })
    for (const chart of [e, p]) { expect(within(chart).getByRole('button', { name: 'Clip 0023' })).toBeInTheDocument(); expect(within(chart).getByRole('button', { name: 'Clip 0024' })).toBeInTheDocument(); expect(within(chart).queryByRole('button', { name: 'Clip 0001' })).not.toBeInTheDocument() }
  })

  it('opens a clip when its marker is clicked or Enter is pressed, and reports hover for the card', async () => {
    const open = vi.fn(), hover = vi.fn(); const { user } = setup(<TrackCharts {...base} onOpenClip={open} onHoverClip={hover} />)
    const m = within(screen.getByRole('group', { name: 'Pace chart' })).getByRole('button', { name: 'Clip 0024' })
    await user.hover(m); expect(hover).toHaveBeenCalledWith(expect.objectContaining({ label: '0024' }), expect.any(Number), expect.any(Number))
    await user.unhover(m); expect(hover).toHaveBeenLastCalledWith(null)
    await user.click(m); expect(open).toHaveBeenCalledWith('CAM_20260222210000_0024_D')
    m.focus(); await user.keyboard('{Enter}'); expect(open).toHaveBeenCalledTimes(2)
  })

  it('shows the shared cursor with the elevation and pace readings, and "stopped" where there is no pace', () => {
    const { rerender } = setup(<TrackCharts {...base} cursor={900 * 5} />)
    expect(document.querySelectorAll('[data-cursor]')).toHaveLength(2); expect(screen.getByText(/ m$/, { selector: 'text' })).toBeInTheDocument(); expect(screen.getByText(/\/km$/, { selector: 'text' })).toBeInTheDocument()
    rerender(<TrackCharts {...base} cursor={900 * 13} />); expect(screen.getByText('stopped')).toBeInTheDocument()
    rerender(<TrackCharts {...base} cursor={null} />); expect(document.querySelectorAll('[data-cursor]')).toHaveLength(0)
  })

  it('moves the cursor with the mouse over a chart, to the point under it', () => {
    const unstub = stubRect(1000, 150); const cur = vi.fn(); setup(<TrackCharts {...base} onCursor={cur} />)
    const rect = screen.getByRole('group', { name: 'Elevation chart' }).querySelector('rect[fill="transparent"]')!
    fireEvent.mouseMove(rect, { clientX: 54 + (1000 - 54 - 12) / 2 })                                          // the middle of the plot
    const t = cur.mock.calls.at(-1)![0] as number; expect(t).toBeGreaterThan(14000); expect(t).toBeLessThan(22000)
    fireEvent.mouseLeave(rect); expect(cur).toHaveBeenLastCalledWith(null); unstub()
  })

  it('shades the stretch where the runner stood still, on both charts', () => {
    setup(<TrackCharts {...base} />); expect(document.querySelectorAll('rect[data-stop]')).toHaveLength(2)
  })

  it('labels the pace axis in min/km, faster at the top, and the time axis with clock times', () => {
    setup(<TrackCharts {...base} />)
    const pace = screen.getByRole('group', { name: 'Pace chart' }); expect(within(pace).getByText(/faster is higher/)).toBeInTheDocument(); expect(within(pace).getByText('6:00')).toBeInTheDocument()
    const ys = [...pace.querySelectorAll('text')].filter(t => /^\d+:\d\d$/.test(t.textContent ?? '') && t.getAttribute('text-anchor') === 'end'); const top = ys.find(t => t.textContent === '6:00')!, low = ys.find(t => t.textContent === '8:00')!
    expect(Number(top.getAttribute('y'))).toBeLessThan(Number(low.getAttribute('y')))                           // 6:00 is drawn above 8:00
    expect([...pace.querySelectorAll('text')].some(t => /^(Sun|Mon|Sat) \d\d:\d\d$/.test(t.textContent ?? ''))).toBe(true)
  })

  it('switches the horizontal axis to distance', () => {
    const { rerender } = setup(<TrackCharts {...base} />); rerender(<TrackCharts {...base} xMode="km" />)
    expect(within(screen.getByRole('group', { name: 'Elevation chart' })).getAllByText(/^\d+ km$/).length).toBeGreaterThan(2)
  })

  it('has no accessibility violations', async () => {
    const { axe } = await import('vitest-axe'); const { container } = setup(<TrackCharts {...base} />); expect(await axe(container)).toHaveNoViolations()
  })
})
