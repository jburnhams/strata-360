import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import RoughMixPlayer from '../../src/components/RoughMixPlayer'
import { screen, setup, waitFor } from '../utils/render'
import { makeRoughMix } from '../utils/factories'
import { mockGet, mockPost, recordRequests } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('RoughMixPlayer', () => {
  it('shows nothing while there is no film plan', async () => {
    mockGet('/api/script2/mix', makeRoughMix({ has_plan: false }))
    const { container } = setup(<RoughMixPlayer folder="/data" />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('offers to make the mix, and starts it', async () => {
    mockGet('/api/script2/mix', makeRoughMix())
    const seen = recordRequests('/api/script2/mix'); mockPost('/api/script2/mix', { started: true })
    const { user } = setup(<RoughMixPlayer folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Make a rough mix' }))
    await waitFor(() => expect(seen.some(r => r.method === 'POST')).toBe(true))
    expect(seen.find(r => r.method === 'POST')?.body).toEqual({ folder: '/data' })
    expect(screen.queryByLabelText('Rough mix')).not.toBeInTheDocument()
  })

  it('shows progress while it is being made and blocks a second start', async () => {
    mockGet('/api/script2/mix', makeRoughMix({ building: true, log: 'mixing' }))
    setup(<RoughMixPlayer folder="/data" />)
    expect(await screen.findByText('mixing')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Making the rough mix…' })).toBeDisabled()
  })

  it('plays a finished mix and says when it is out of date', async () => {
    mockGet('/api/script2/mix', makeRoughMix({ exists: true, stale: true, length_s: 248, made_at: '2026-10-02T09:00:00' }))
    setup(<RoughMixPlayer folder="/data" />)
    const audio = await screen.findByLabelText('Rough mix')
    expect(audio).toHaveAttribute('src', '/api/script2/mix/audio?folder=%2Fdata&v=2026-10-02T09%3A00%3A00')
    expect(screen.getByText(/out of date/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Make the rough mix again' })).toBeInTheDocument()
  })

  it('shows the reason a start was refused and the error of a failed run', async () => {
    mockGet('/api/script2/mix', makeRoughMix({ error: 'no voice is installed: run voice setup' }))
    mockPost('/api/script2/mix', { started: false, reason: 'the rough mix is already being made' })
    const { user } = setup(<RoughMixPlayer folder="/data" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The rough mix failed: no voice is installed')
    await user.click(screen.getByRole('button', { name: 'Make a rough mix' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already being made')
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/script2/mix', makeRoughMix({ exists: true, made_at: 'x' }))
    const { container } = setup(<RoughMixPlayer folder="/data" />)
    await screen.findByLabelText('Rough mix')
    expect(await axe(container)).toHaveNoViolations()
  })
})
