import { expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import { mockError, mockGet, recordRequests } from '../utils/api'
import { setup, screen } from '../utils/render'
import { makeOverlayState } from '../utils/factories'
import OverlaySettings from '../../src/components/OverlaySettings'

const open = async (user: ReturnType<typeof setup>['user']) => { await user.click(await screen.findByText('Overlay')) }

it('shows the saved settings and how many elements are drawn', async () => {
  const { user } = setup(<OverlaySettings folder="/f" />)
  expect(await screen.findByText(/3 elements/)).toBeInTheDocument(); await open(user)
  expect(screen.getByLabelText('Clock and date')).toBeChecked(); expect(screen.getByLabelText('Pace')).not.toBeChecked()
  expect(screen.getByLabelText('Whole-route map style')).toHaveValue('tf-landscape'); expect(screen.getByLabelText('Close-up zoom')).toHaveValue(14)
  expect(screen.getByText('set')).toBeInTheDocument(); expect(screen.getByText(/12 map tiles cached/)).toBeInTheDocument()
})

it('saves the changed settings, keeping the elements in the layout order', async () => {
  const reqs = recordRequests('/api/overlay')
  const { user } = setup(<OverlaySettings folder="/f" />); await open(user)
  expect(screen.getByRole('button', { name: 'Save overlay settings' })).toBeDisabled()
  await user.click(screen.getByLabelText('Pace')); await user.selectOptions(screen.getByLabelText('Close-up map style'), 'osm'); await user.click(screen.getByLabelText('Zoom by itself'))
  await user.clear(screen.getByLabelText('Close-up zoom')); await user.type(screen.getByLabelText('Close-up zoom'), '12')
  await user.click(screen.getByRole('button', { name: 'Save overlay settings' }))
  await vi.waitFor(() => expect(reqs.filter(r => r.method === 'POST')).toHaveLength(1))
  expect(reqs.find(r => r.method === 'POST')!.body).toMatchObject({ folder: '/f', elements: ['clock', 'distance', 'pace', 'route_map'], local_style: 'osm', auto_zoom: false, local_zoom: 12 })
  expect(await screen.findByText(/saved; the overlay thumbnails/)).toBeInTheDocument(); expect(screen.getByText(/4 elements/)).toBeInTheDocument()
})

it('turning the overlay off greys out the elements and says so', async () => {
  const { user } = setup(<OverlaySettings folder="/f" />); await open(user)
  await user.click(screen.getByLabelText('Draw the race overlay on the film'))
  expect(screen.getByLabelText('Distance')).toBeDisabled(); expect(screen.getByText(/· off/)).toBeInTheDocument()
})

it('undo puts back the saved settings', async () => {
  const { user } = setup(<OverlaySettings folder="/f" />); await open(user)
  await user.click(screen.getByLabelText('Pace')); await user.click(screen.getByRole('button', { name: 'undo changes' }))
  expect(screen.getByLabelText('Pace')).not.toBeChecked(); expect(screen.getByRole('button', { name: 'Save overlay settings' })).toBeDisabled()
})

it('a refused save shows the server\'s reason', async () => {
  mockError('/api/overlay', 400, 'local_zoom: between 3 and 18', 'post')
  const { user } = setup(<OverlaySettings folder="/f" />); await open(user)
  await user.click(screen.getByLabelText('Pace')); await user.click(screen.getByRole('button', { name: 'Save overlay settings' }))
  expect(await screen.findByText('local_zoom: between 3 and 18')).toBeInTheDocument()
})

it('a missing key is flagged when a chosen map needs one, and the key is sent and cleared from the field', async () => {
  mockGet('/api/overlay', () => makeOverlayState({ key_set: false }))
  const reqs = recordRequests('/api/overlay/key')
  const { user } = setup(<OverlaySettings folder="/f" />)
  expect(await screen.findByText(/map key missing/)).toBeInTheDocument(); await open(user)
  expect(screen.getByText(/not set, the maps need it/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Save key' })).toBeDisabled()
  await user.type(screen.getByLabelText('Map key'), 'abc123def456'); await user.click(screen.getByRole('button', { name: 'Save key' }))
  await vi.waitFor(() => expect(reqs).toHaveLength(1)); expect(reqs[0].body).toEqual({ key: 'abc123def456' })
  expect(await screen.findByText('set')).toBeInTheDocument(); expect(screen.getByLabelText('Map key')).toHaveValue('')
})

it('the key can be removed', async () => {
  const reqs = recordRequests('/api/overlay/key')
  const { user } = setup(<OverlaySettings folder="/f" />); await open(user)
  await user.click(screen.getByRole('button', { name: 'remove key' }))
  await vi.waitFor(() => expect(reqs).toHaveLength(1)); expect(reqs[0].body).toEqual({ key: '' })
  expect(await screen.findByText(/not set, the maps need it/)).toBeInTheDocument()
})

it('no key is needed for maps that do not use one', async () => {
  mockGet('/api/overlay', () => makeOverlayState({ key_set: false }, { route_style: 'osm', local_style: 'osm' }))
  const { user } = setup(<OverlaySettings folder="/f" />); await open(user)
  expect(screen.queryByText(/map key missing/)).toBeNull(); expect(screen.getByText('not set')).toBeInTheDocument()
})

it('nothing can be changed while the film is rendering', async () => {
  const { user } = setup(<OverlaySettings folder="/f" disabled />); await open(user)
  expect(screen.getByLabelText('Draw the race overlay on the film')).toBeDisabled(); expect(screen.getByLabelText('Map key')).toBeDisabled()
})

it('a failure to load the settings is shown', async () => {
  mockError('/api/overlay', 400, 'race.json overlay: unknown overlay element(s) nope')
  setup(<OverlaySettings folder="/f" />)
  expect(await screen.findByText(/unknown overlay element/)).toBeInTheDocument()
})

it('has no accessibility violations', async () => {
  const { user, container } = setup(<OverlaySettings folder="/f" />); await open(user)
  expect(await axe(container)).toHaveNoViolations()
})
