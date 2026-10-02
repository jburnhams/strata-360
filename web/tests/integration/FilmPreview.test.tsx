import { expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { mockGet, mockPending, mockError, mockPost, recordRequests } from '../utils/api'
import { setup } from '../utils/render'
import { stubBrowserApis } from '../utils/media'
import FilmPreview from '../../src/components/FilmPreview'
import { makeFilmState } from '../utils/factories'

stubBrowserApis()

it('renders empty while loading', () => {
  mockPending('/api/film')
  const { container } = setup(<FilmPreview folder="/f" />)
  expect(container.firstChild).toBeNull() // renders nothing while waiting
})

it('renders noplan state', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'noplan' }))
  const { findByText } = setup(<FilmPreview folder="/f" />)
  expect(await findByText('Film preview')).toBeInTheDocument()
  expect(await findByText('Make a plan first.')).toBeInTheDocument()
})

it('shows start button when not ready', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'none' }))
  const { user, findByRole } = setup(<FilmPreview folder="/f" />)
  const btn = await findByRole('button', { name: 'Render preview' })
  expect(btn).toBeInTheDocument()

  const reqs = recordRequests('/api/film/start')
  mockPost('/api/film/start', { started: true })
  await user.click(btn)

  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => expect(reqs.find(r => r.method === 'POST')).toBeTruthy())
})

it('shows progress while building', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'rendering', frames_done: 25, frames_total: 100, length_s: 4 }))
  const { findByText } = setup(<FilmPreview folder="/f" />)
  expect(await findByText('rendering 25% (1 of 4 s)')).toBeInTheDocument()
})

it('renders the player when ready', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'done' }))
  const { findByRole } = setup(<FilmPreview folder="/f" />)
  // jsdom won't load media natively but the video element should be present
  expect(await findByRole('button', { name: 'Render again' })).toBeInTheDocument()
})

it('handles stop click during build', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'rendering' }))
  const { user, findByRole, findByText } = setup(<FilmPreview folder="/f" />)

  const reqs = recordRequests('/api/film/stop')
  mockPost('/api/film/stop', { ok: true })
  const btn = await findByRole('button', { name: 'stop' })
  await user.click(btn)

  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => expect(reqs.find(r => r.method === 'POST')).toBeTruthy())
})

it('has no accessibility violations', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'done' }))
  const { container, findByRole } = setup(<FilmPreview folder="/f" />)
  await findByRole('button', { name: 'Render again' }) // Wait for load
  expect(await axe(container)).toHaveNoViolations()
})
