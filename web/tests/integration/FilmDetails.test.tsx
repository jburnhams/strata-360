import { expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { mockGet, mockPending, recordRequests, mockError, mockPost } from '../utils/api'
import { setup } from '../utils/render'
import { makeMeta } from '../utils/factories'
import FilmDetails from '../../src/components/FilmDetails'

it('renders a skeleton while loading', async () => {
  mockPending('/api/meta')
  const { findByText } = setup(<FilmDetails folder="/f" />)
  expect(await findByText('Film details')).toBeInTheDocument()
})

it('renders details once loaded', async () => {
  mockGet('/api/meta', () => makeMeta({ title: 'Test Title', effective: { title: 'Test Title', date: '2023-01-01' } }))
  const { findByDisplayValue } = setup(<FilmDetails folder="/f" />)
  expect(await findByDisplayValue('Test Title')).toBeInTheDocument()
  expect(await findByDisplayValue('2023-01-01')).toBeInTheDocument()
})

it('saves changes to title', async () => {
  mockGet('/api/meta', () => makeMeta({ title: 'Test Title', defaults: { title: 'Race or film title', date: null, earliest_capture_utc: null }, effective: { title: 'Test Title', date: '2023-01-01' } }))
  const { user, findByPlaceholderText, findByDisplayValue } = setup(<FilmDetails folder="/f" />)

  await findByDisplayValue('Test Title') // wait for load
  const reqs = recordRequests('/api/meta')

  const title = await findByPlaceholderText('Race or film title')
  await user.clear(title)
  await user.type(title, 'New Title')
  await user.click(document.body) // blur

  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.title === 'New Title')).toBeTruthy(), { timeout: 1000 })
})

it.todo('saves changes to date (flaky due to input[type="date"] and React synthetic onChange in jsdom)')

it('saves changes to race results', async () => {
  mockGet('/api/meta', () => makeMeta({ title: 'Test Title', defaults: { title: 'Race or film title', date: null, earliest_capture_utc: null }, effective: { title: 'Test Title', date: '2023-01-01' } }))
  const { user, findByLabelText, findByDisplayValue } = setup(<FilmDetails folder="/f" />)

  await findByDisplayValue('Test Title') // wait for load
  const reqs = recordRequests('/api/meta')

  const { waitFor, fireEvent } = await import('@testing-library/react')
  const starters = await findByLabelText('Starters')
  fireEvent.change(starters, { target: { value: '100' } })
  fireEvent.blur(starters)
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.results?.starters === 100)).toBeTruthy(), { timeout: 1000 })

  const finishers = await findByLabelText('Finishers')
  fireEvent.change(finishers, { target: { value: '90' } })
  fireEvent.blur(finishers)
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.results?.finishers === 90)).toBeTruthy(), { timeout: 1000 })

  const you = await findByLabelText('You')
  await user.selectOptions(you, 'yes')
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.results?.finished === true)).toBeTruthy(), { timeout: 1000 })

  const position = await findByLabelText('Your position')
  fireEvent.change(position, { target: { value: '5' } })
  fireEvent.blur(position)
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.results?.position === 5)).toBeTruthy(), { timeout: 1000 })
})

it('clears race results on empty input', async () => {
  mockGet('/api/meta', () => makeMeta({ title: 'Test Title', results: { starters: 100, finishers: null, finished: null, position: null }, defaults: { title: 'Race or film title', date: null, earliest_capture_utc: null }, effective: { title: 'Test Title', date: '2023-01-01' } }))
  const { user, findByLabelText, findByDisplayValue } = setup(<FilmDetails folder="/f" />)

  await findByDisplayValue('Test Title') // wait for load
  const reqs = recordRequests('/api/meta')

  const { waitFor, fireEvent } = await import('@testing-library/react')
  const starters = await findByLabelText('Starters')

  fireEvent.change(starters, { target: { value: '' } })
  fireEvent.blur(starters)
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.results?.starters === null)).toBeTruthy(), { timeout: 1000 })
})

it('shows an error if save fails', async () => {
  mockGet('/api/meta', () => makeMeta({ title: 'Test Title', defaults: { title: 'Race or film title', date: null, earliest_capture_utc: null }, effective: { title: 'Test Title', date: '2023-01-01' } }))
  const { user, findByPlaceholderText, findByText, findByDisplayValue } = setup(<FilmDetails folder="/f" />)
  await findByDisplayValue('Test Title') // wait for load
  mockError('/api/meta', 500, 'Server error', 'post')
  const title = await findByPlaceholderText('Race or film title')
  await user.clear(title)
  await user.type(title, 'Fail Title')
  await user.click(document.body) // blur
  expect(await findByText('Server error')).toBeInTheDocument()
})

it('uses earliest capture when button is clicked', async () => {
  // m.date must NOT be null for the button to appear.
  mockGet('/api/meta', () => makeMeta({ date: '2023-01-05', effective: { title: null, date: '2023-01-05' }, defaults: { title: null, date: '2023-01-01', earliest_capture_utc: null } }))
  const { user, findByText } = setup(<FilmDetails folder="/f" />)

  const { waitFor, screen } = await import('@testing-library/react')
  await waitFor(async () => expect(await screen.findByText('use earliest capture')).toBeInTheDocument(), { timeout: 1000 }) // Wait for loaded state

  const btn = await findByText('use earliest capture')
  const reqs = recordRequests('/api/meta')
  await user.click(btn)
  await waitFor(() => expect(reqs.find(r => r.method === 'POST' && (r.body as any)?.date === '')).toBeTruthy())
})

it('has no accessibility violations', async () => {
  const { container, findByDisplayValue } = setup(<FilmDetails folder="/f" />)
  await findByDisplayValue('Test Title') // wait for load
  expect(await axe(container)).toHaveNoViolations()
})
