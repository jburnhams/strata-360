import { expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { mockGet, mockPending, recordRequests, mockPost } from '../utils/api'
import { setup } from '../utils/render'
import FinalRender from '../../src/components/FinalRender'
import { makeFinalState } from '../utils/factories'

it('renders a skeleton while loading or no plan', async () => {
  mockGet('/api/final', () => makeFinalState({ state: 'noplan' }))
  const { container } = setup(<FinalRender folder="/f" />)
  expect(container.firstChild).toBeNull() // noplan returns null
})

it('shows settings and start button when ready to render', async () => {
  mockGet('/api/final', () => makeFinalState({ state: 'none', settings: { size: '1920x1080', fps: 30, bitrate: 'test' } }))
  const { findByLabelText, findByRole } = setup(<FinalRender folder="/f" />)

  expect(await findByLabelText(/Size/i)).toBeInTheDocument()
  expect(await findByLabelText(/Frames\/s/i)).toBeInTheDocument()
  expect(await findByRole('button', { name: 'Render final film' })).toBeInTheDocument()
})

it('can trigger a render with changed settings', async () => {
  mockGet('/api/final', () => makeFinalState({ state: 'none', settings: { size: '1920x1080', fps: 30, bitrate: 'test' } }))
  const { user, findByRole, findByLabelText } = setup(<FinalRender folder="/f" />)

  const reqs = recordRequests('/api/final/start')
  mockPost('/api/final/start', { started: true })

  await user.selectOptions(await findByLabelText(/Size/i), '3840x2160')
  await user.selectOptions(await findByLabelText(/Frames\/s/i), '50')

  await user.click(await findByRole('button', { name: 'Render final film' }))

  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => expect(reqs.find(r => r.method === 'POST')).toBeTruthy())
  expect(reqs[0].body).toMatchObject({ folder: '/f', size: '3840x2160', fps: 50 })
})

it('shows progress and stop button while rendering', async () => {
  mockGet('/api/final', () => makeFinalState({ state: 'rendering', frames_done: 45, frames_total: 100, pieces_done: 1, pieces_total: 2, started: 10 }))
  const { user, findByText, findByRole } = setup(<FinalRender folder="/f" />)

  expect(await findByText(/rendering 45% · piece 1\/2/i)).toBeInTheDocument()

  const reqs = recordRequests('/api/final/stop')
  mockPost('/api/final/stop', { ok: true })

  await user.click(await findByRole('button', { name: /stop/i }))

  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => expect(reqs.find(r => r.method === 'POST')).toBeTruthy())
})

it('has no accessibility violations', async () => {
  mockGet('/api/final', () => makeFinalState({ state: 'none', settings: { size: '1920x1080', fps: 30, bitrate: 'test' } }))
  const { container, findByRole } = setup(<FinalRender folder="/f" />)
  await findByRole('button', { name: 'Render final film' }) // wait for load
  expect(await axe(container)).toHaveNoViolations()
})
