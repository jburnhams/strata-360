import { describe, expect, it, vi } from 'vitest'
import { screen, setup } from '../utils/render'
import StopsTable from '../../src/components/StopsTable'
import { stopFacts } from '../../src/mapLayers'
import type { Poi } from '../../src/api'

const stop = (n: number, o: Partial<Poi> = {}): Poi => ({ name: `Stop ${n}`, lat: 50, lon: 5, ele: null, sym: 'stop', desc: 'km 114.9 of the run', track: '', stop: { arrived: 1_771_600_000, left: 1_771_603_120, stopped_s: 3120, radius_m: 60 }, ...o })

describe('the other stops', () => {
  it('lists each stop with where, when and how long, and ignores checkpoints and other points', () => {
    setup(<StopsTable tz="Europe/Brussels" pois={[stop(1), stop(2, { desc: 'km 165.9 of the run' }), { ...stop(3), sym: 'checkpoint', name: 'Checkpoint 3' }]} />)
    expect(screen.getByText('(2)')).toBeInTheDocument(); const row = document.querySelector('[data-stop-row="Stop 1"]')!
    expect(row).toHaveTextContent('114.9'); expect(row).toHaveTextContent('52 min'); expect(row).toHaveTextContent('60 m'); expect(row).toHaveTextContent(/Fri 20 Feb \d\d:\d\d/); expect(document.querySelector('[data-stop-row="Checkpoint 3"]')).toBeNull()
  })

  it('says so when there are none, with the rule', () => {
    setup(<StopsTable tz="UTC" pois={[]} />); expect(screen.getByText(/No stop of ten minutes or more in one small place/)).toBeInTheDocument()
  })

  it('gives the map card and the table the same facts', () => {
    const f = stopFacts(stop(1), 'UTC'); expect(f).toMatchObject({ name: 'Stop 1', km: 114.9, duration: '52 min 00 s', area_m: 60 }); expect(f.arrived).toMatch(/Fri 20 Feb/)
  })

  it('has an add to video button for a stop, and shows the gap it became with a way to take it out', async () => {
    const toggle = vi.fn(), open = vi.fn(); const { user, rerender } = setup(<StopsTable tz="UTC" onToggle={toggle} onOpenGap={open} pois={[stop(1, { key: 'k1', added: false })]} />)
    await user.click(screen.getByRole('button', { name: 'Add Stop 1 to the video' })); expect(toggle).toHaveBeenCalledWith('k1', true)
    rerender(<StopsTable tz="UTC" onToggle={toggle} onOpenGap={open} pois={[stop(1, { key: 'k1', added: true, gap: 'G05' })]} />)
    await user.click(screen.getByRole('button', { name: 'as G05' })); expect(open).toHaveBeenCalledWith('G05'); await user.click(screen.getByRole('button', { name: 'Take Stop 1 out of the video' })); expect(toggle).toHaveBeenCalledWith('k1', false)
  })
})
