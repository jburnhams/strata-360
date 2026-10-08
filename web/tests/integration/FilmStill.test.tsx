import { expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { waitFor } from '@testing-library/react'
import { mockError, mockGet, mockPost, recordRequests } from '../utils/api'
import { setup } from '../utils/render'
import { stubBrowserApis } from '../utils/media'
import FilmStill from '../../src/components/FilmStill'
import { makeRenderProgress, makeStillList, makeStillMeta } from '../utils/factories'

stubBrowserApis()

const player = (t: number) => ({ current: { currentTime: t } as HTMLVideoElement })
const HERE = 'Render still at the player position'

it('asks for the frame at the player position, at 4K without enlarging by default', async () => {
  mockPost('/api/film/still', { name: 'x_f1.png', state: 'rendering' })
  const seen = recordRequests('/api/film/still')
  const { user, findByRole } = setup(<FilmStill folder="/f" video={player(83.4)} />)
  await user.click(await findByRole('button', { name: HERE }))
  await waitFor(() => expect(seen.find(r => r.method === 'POST')?.body).toEqual({ folder: '/f', t: 83.4, size: '3840x2160', upscale: 'off' }))
})

it('sends the size and the enlarge mode picked from the dropdowns', async () => {
  mockPost('/api/film/still', { name: 'x_f1.png', state: 'rendering' })
  const seen = recordRequests('/api/film/still')
  const { user, findByRole, getByLabelText } = setup(<FilmStill folder="/f" video={player(5)} />)
  await user.selectOptions(getByLabelText('Size'), '1920x1080'); await user.selectOptions(getByLabelText(/Enlarge/), '1440p')
  await user.click(await findByRole('button', { name: HERE }))
  await waitFor(() => expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ size: '1920x1080', upscale: '1440p' }))
})

it('offers each enlarge mode by what it does', async () => {
  const { getByLabelText } = setup(<FilmStill folder="/f" video={player(1)} />)
  expect(Array.from((getByLabelText(/Enlarge/) as HTMLSelectElement).options).map(o => o.text)).toEqual(['No enlarging', 'Model to 1080p, then resample', 'Model to 1440p, then resample', 'Model to the full output size'])
})

it('the Auto button says how many moments the film gets and asks for that series', async () => {
  mockGet('/api/film/stills', makeStillList({ auto_count: 6 })); mockPost('/api/film/still', { moments: [] })
  const seen = recordRequests('/api/film/still')
  const { user, findByRole, getByLabelText } = setup(<FilmStill folder="/f" video={player(1)} />)
  await user.selectOptions(getByLabelText(/Enlarge/), '1080p')
  await user.click(await findByRole('button', { name: 'Auto: 6 differing moments' }))
  await waitFor(() => expect(seen.find(r => r.method === 'POST')?.body).toEqual({ folder: '/f', size: '3840x2160', upscale: '1080p', auto: true }))
})

it('shows what is being made and how many are to go', async () => {
  mockGet('/api/film/stills', makeStillList({ active: [
    { name: 'a_f1.png', state: 'rendering', t: 83.4, size: '3840x2160', upscale: '1080p', progress: makeRenderProgress({ state: 'running' }) },
    { name: 'b_f2.png', state: 'queued', t: 120, size: '3840x2160', upscale: '1080p', label: 'footage, wide (90°)' }] }))
  const { findByRole, findByText } = setup(<FilmStill folder="/f" video={player(1)} />)
  expect(await findByRole('status')).toHaveTextContent('2 stills to go · now the frame at 1:23.4 (model to 1080p) · 4K')
  expect(await findByText('Where the time goes inside the render')).toBeInTheDocument()       // the running one's steps and timings
})

it('shows the waiting and rendering tiles in the gallery', async () => {
  mockGet('/api/film/stills', makeStillList({ active: [{ name: 'a_f1.png', state: 'rendering', t: 83.4, size: '3840x2160', upscale: 'off' }, { name: 'b_f2.png', state: 'queued', t: 120, size: '3840x2160', upscale: 'off', label: 'footage, tight (58°)' }] }))
  const { findByLabelText, getByLabelText } = setup(<FilmStill folder="/f" video={player(1)} />)
  expect(await findByLabelText('Still rendering')).toHaveTextContent('rendering…'); expect(getByLabelText('Still queued')).toHaveTextContent('footage, tight (58°)')
})

it('shows a failed still and why', async () => {
  mockGet('/api/film/stills', makeStillList({ active: [{ name: 'a_f1.png', state: 'error', t: 10, error: 'enlarging needs the spandrel package' }] }))
  const { findByText } = setup(<FilmStill folder="/f" video={player(1)} />)
  expect(await findByText(/The still at 0:10.0 failed: enlarging needs the spandrel package/)).toBeInTheDocument()
})

it('shows what went wrong when the request is refused', async () => {
  mockError('/api/film/still', 400, 'make a plan first', 'post')
  const { user, findByRole, findByText } = setup(<FilmStill folder="/f" video={player(1)} />)
  await user.click(await findByRole('button', { name: HERE })); expect(await findByText(/make a plan first/)).toBeInTheDocument()
})

it('lists the stills already made, with the gallery', async () => {
  mockGet('/api/film/stills', makeStillList({ stills: [makeStillMeta(), makeStillMeta({ name: 'b_f2.png', t: 10, upscale: 'full' })] }))
  const { findByText, getAllByRole } = setup(<FilmStill folder="/f" video={player(1)} />)
  expect(await findByText('All stills (2)')).toBeInTheDocument(); expect(getAllByRole('listitem')).toHaveLength(2)
})

it('has no accessibility violations', async () => {
  mockGet('/api/film/stills', makeStillList({ stills: [makeStillMeta()] }))
  const { container, findByText } = setup(<FilmStill folder="/f" video={player(3)} />)
  await findByText('All stills (1)'); expect(await axe(container)).toHaveNoViolations()
})
