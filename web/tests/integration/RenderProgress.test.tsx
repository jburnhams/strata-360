import { afterEach, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import { act } from '@testing-library/react'
import { setup } from '../utils/render'
import RenderProgress, { dur } from '../../src/components/RenderProgress'
import { makeRenderProgress } from '../utils/factories'

afterEach(() => { vi.useRealTimers() })

it('writes seconds under a minute and minutes and seconds over', () => {
  expect([dur(0), dur(12.34), dur(59.9), dur(60), dur(187)]).toEqual(['0.0 s', '12.3 s', '59.9 s', '1:00', '3:07'])
})

it('renders nothing before the render has reported', () => {
  const { container } = setup(<RenderProgress progress={null} busy />)
  expect(container.firstChild).toBeNull()
})

it('lists the steps in order with their times', () => {
  const { getAllByRole } = setup(<RenderProgress progress={makeRenderProgress()} busy={false} />)
  const items = getAllByRole('listitem'); expect(items.map(i => i.textContent)).toEqual([
    '✓prepareglides, exposure match, overlay3.2 s', '✓load modelrealplksr-nomos1.5 s', '✓renderframe 5 of 51:15'])
})

it('orders the time spent by size, with shares and counts', () => {
  const { getAllByRole } = setup(<RenderProgress progress={makeRenderProgress()} busy={false} />)
  const rows = getAllByRole('row').map(r => r.textContent)
  expect(rows[0]).toContain('enlarging (model)'); expect(rows[0]).toContain('93%'); expect(rows[0]).toContain('5 calls')
  expect(rows[1]).toContain('projecting the view'); expect(rows[2]).toContain('drawing the overlay')
})

it('counts the running step up between polls', () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date(1030 * 1000))
  const p = makeRenderProgress({ state: 'running', stages: [{ name: 'render', state: 'running', started: 1000, seconds: 5, detail: 'piece 2 of 9' }] })
  const { getByText } = setup(<RenderProgress progress={p} busy />)
  expect(getByText('30.0 s')).toBeInTheDocument()                           // 30 s since it started, not the 5 s of the last write
  act(() => { vi.advanceTimersByTime(12000) })                              // twelve more seconds of ticks
  expect(getByText('42.0 s')).toBeInTheDocument()
})

it('shows a failure', () => {
  const { getByText, getAllByText } = setup(<RenderProgress progress={makeRenderProgress({ state: 'error', error: 'the model weights are missing', stages: [{ name: 'load model', state: 'error', started: 1000, seconds: 0.2, detail: '' }] })} busy={false} />)
  expect(getByText('the model weights are missing')).toBeInTheDocument(); expect(getAllByText('✗')).toHaveLength(1)
})

it('keeps the log open while busy and closed when finished', () => {
  const a = setup(<RenderProgress progress={makeRenderProgress()} busy />); expect(a.container.querySelector('details')).toHaveAttribute('open'); a.unmount()
  const b = setup(<RenderProgress progress={makeRenderProgress()} busy={false} />); expect(b.container.querySelector('details')).not.toHaveAttribute('open')
})

it('has no accessibility violations', async () => {
  const { container } = setup(<RenderProgress progress={makeRenderProgress()} busy={false} />)
  expect(await axe(container)).toHaveNoViolations()
})
