import { expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { fireEvent, within } from '@testing-library/react'
import { setup } from '../utils/render'
import StillGallery from '../../src/components/StillGallery'
import { makeStillMeta } from '../utils/factories'
import type { StillMeta } from '../../src/api'

const three: StillMeta[] = [
  makeStillMeta({ name: 'a_f100.png', t: 2, frame: 100, upscale: 'off', modified: 300, seconds: 10 }),
  makeStillMeta({ name: 'b_f500.png', t: 10, frame: 500, upscale: '1080p', modified: 200, seconds: 25, shots: [{ id: 'w3', clip: 'CAM_X', fov: 45, factor: 2, note: '' }] }),
  makeStillMeta({ name: 'c_f050.png', t: 1, frame: 50, upscale: 'full', modified: 100, current: false, seconds: 90 }),
]
const names = (c: HTMLElement) => within(c).getAllByRole('listitem').map(li => li.querySelector('p')?.textContent)

it('says so when there are none', () => {
  const { getByText } = setup(<StillGallery folder="/f" stills={[]} active={[]} />); expect(getByText(/No stills yet/)).toBeInTheDocument()
})

it('renders nothing while the list is loading', () => {
  const { container } = setup(<StillGallery folder="/f" stills={[]} active={[]} loading />); expect(container.firstChild).toBeNull()
})

it('shows a thumbnail with its time, size and enlarging for each', () => {
  const { getAllByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  const li = getAllByRole('listitem'); expect(li).toHaveLength(3)
  expect(li[1].textContent).toContain('0:10.0 · 4K'); expect(li[1].textContent).toContain('model to 1080p'); expect(li[0].textContent).toContain('no enlarging')
  expect(li[1].querySelector('img')?.getAttribute('src')).toContain('/api/film/still/thumb?')
})

it('lists the newest first and can list by film time', async () => {
  const { container, user, getByLabelText } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  expect(names(container)).toEqual(['0:02.0 · 4K', '0:10.0 · 4K', '0:01.0 · 4K'])
  await user.selectOptions(getByLabelText('Order'), 'film'); expect(names(container)).toEqual(['0:01.0 · 4K', '0:02.0 · 4K', '0:10.0 · 4K'])
})

it('marks stills from an older plan and can hide them', async () => {
  const { getAllByText, user, getByLabelText, getAllByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  expect(getAllByText('older plan')).toHaveLength(1)
  await user.click(getByLabelText('Only the current plan')); expect(getAllByRole('listitem')).toHaveLength(2)
})

it('has no filter for the current plan when all are current', () => {
  const { queryByLabelText } = setup(<StillGallery folder="/f" stills={three.slice(0, 2)} active={[]} />); expect(queryByLabelText('Only the current plan')).toBeNull()
})

it('lists a still from before the details were kept by its frame', () => {
  const { getByText } = setup(<StillGallery folder="/f" stills={[makeStillMeta({ name: 'z_f250.png', frame: 250, t: null, size: null, upscale: null, legacy: true, rendered: undefined })]} active={[]} />)
  expect(getByText('frame 250')).toBeInTheDocument(); expect(getByText('made before details were kept')).toBeInTheDocument()
})

it('opens a viewer with everything kept about the still', async () => {
  const { user, getAllByRole, getByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  await user.click(within(getAllByRole('listitem')[1]).getByRole('button'))
  const d = getByRole('dialog', { name: 'Still viewer' }), det = within(d).getByLabelText('Details of the still').textContent!
  expect(det).toContain('Film time0:10.0'); expect(det).toContain('3840×2160 (4K)'); expect(det).toContain('Model to 1080p, then resample'); expect(det).toContain('narrowest view 45°'); expect(det).toContain('enlarged ×2')
  expect(det).toContain('Took25.0 s'); expect(det).toContain('prepare 1.5 s · render 12.6 s'); expect(det).toContain('reading the video 2.3 s'); expect(det).toContain('the current plan')
  expect(within(d).getByText('download PNG')).toHaveAttribute('download', 'b_f500.png')
})

it('explains a shot that was not enlarged', async () => {
  const s = makeStillMeta({ upscale: 'full', shots: [{ id: 'w1', clip: 'CAM', fov: 90, factor: 1, note: 'night: the sun is -30 degrees' }] })
  const { user, getByRole } = setup(<StillGallery folder="/f" stills={[s]} active={[]} />); await user.click(getByRole('button', { name: /Open the still/ }))
  expect(getByRole('dialog').textContent).toContain('not enlarged (night: the sun is -30 degrees)')
})

it('steps through the stills with the arrow keys and closes on Escape', async () => {
  const { user, getAllByRole, getByRole, queryByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  await user.click(within(getAllByRole('listitem')[0]).getByRole('button')); const title = () => getByRole('dialog').querySelector('span')?.textContent
  expect(title()).toContain('0:02.0'); fireEvent.keyDown(window, { key: 'ArrowRight' }); expect(title()).toContain('0:10.0')
  fireEvent.keyDown(window, { key: 'ArrowLeft' }); fireEvent.keyDown(window, { key: 'ArrowLeft' }); expect(title()).toContain('0:01.0')           // wraps round
  fireEvent.keyDown(window, { key: 'Escape' }); expect(queryByRole('dialog')).toBeNull()
})

it('steps with the buttons and closes with the button, giving the focus back', async () => {
  const { user, getAllByRole, getByRole, queryByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  const open = within(getAllByRole('listitem')[0]).getByRole('button'); await user.click(open)
  await user.click(getByRole('button', { name: 'Next still' })); expect(getByRole('dialog').querySelector('span')?.textContent).toContain('0:10.0')
  await user.click(getByRole('button', { name: 'close' })); expect(queryByRole('dialog')).toBeNull()
})

it('has no step buttons with a single still', async () => {
  const { user, getByRole, queryByRole } = setup(<StillGallery folder="/f" stills={[three[0]]} active={[]} />); await user.click(getByRole('button', { name: /Open the still/ })); expect(queryByRole('button', { name: 'Next still' })).toBeNull()
})

it('compares the ticked stills side by side at full size, with their details', async () => {
  const { user, getAllByRole, queryByRole, getByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  await user.click(within(getAllByRole('listitem')[0]).getByRole('checkbox')); expect(queryByRole('region', { name: 'Comparison' })).toBeNull()          // one is not a comparison
  await user.click(within(getAllByRole('listitem')[1]).getByRole('checkbox'))
  const c = getByRole('region', { name: 'Comparison' }); expect(within(c).getAllByRole('img')).toHaveLength(2); expect(c.textContent).toContain('no enlarging'); expect(c.textContent).toContain('model to 1080p'); expect(c.textContent).toContain('took 25.0 s')
  expect(within(c).getAllByRole('img')[0].getAttribute('src')).toContain('/api/film/still/file?')
})

it('keeps the scrolling of compared pictures together', async () => {
  const { user, getAllByRole, getByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  for (const i of [0, 1]) await user.click(within(getAllByRole('listitem')[i]).getByRole('checkbox'))
  const [a, b] = Array.from(getByRole('region', { name: 'Comparison' }).querySelectorAll('[aria-label^="Full size picture"]')) as HTMLDivElement[]
  a.scrollLeft = 120; a.scrollTop = 40; fireEvent.scroll(a); expect([b.scrollLeft, b.scrollTop]).toEqual([120, 40])
})

it('compares at most four, dropping the oldest tick', async () => {
  const many = Array.from({ length: 5 }, (_, i) => makeStillMeta({ name: `s${i}_f${i}.png`, t: i, modified: 100 - i }))
  const { user, getAllByRole, getByRole } = setup(<StillGallery folder="/f" stills={many} active={[]} />)
  for (let i = 0; i < 5; i++) await user.click(within(getAllByRole('listitem')[i]).getByRole('checkbox'))
  expect(within(getByRole('region', { name: 'Comparison' })).getAllByRole('img')).toHaveLength(4)
})

it('clears the comparison', async () => {
  const { user, getAllByRole, getByRole, queryByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  for (const i of [0, 1]) await user.click(within(getAllByRole('listitem')[i]).getByRole('checkbox'))
  await user.click(getByRole('button', { name: 'clear comparison (2)' })); expect(queryByRole('region', { name: 'Comparison' })).toBeNull()
})

it('drops a ticked still that no longer exists', async () => {
  const { user, getAllByRole, rerender, queryByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  for (const i of [0, 1]) await user.click(within(getAllByRole('listitem')[i]).getByRole('checkbox'))
  rerender(<StillGallery folder="/f" stills={three.slice(0, 1)} active={[]} />); expect(queryByRole('region', { name: 'Comparison' })).toBeNull()
})

it('has no accessibility violations, in the grid, the viewer or the comparison', async () => {
  const { container, user, getAllByRole, getByRole } = setup(<StillGallery folder="/f" stills={three} active={[]} />)
  expect(await axe(container)).toHaveNoViolations()
  for (const i of [0, 1]) await user.click(within(getAllByRole('listitem')[i]).getByRole('checkbox'))
  expect(await axe(container)).toHaveNoViolations()
  await user.click(within(getAllByRole('listitem')[0]).getByRole('button')); expect(await axe(getByRole('dialog'))).toHaveNoViolations()
})
