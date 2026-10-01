import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import ClockPanel from '../../src/components/ClockPanel'
import { screen, setup } from '../utils/render'
import { makeClockState } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('ClockPanel', () => {
  it('renders nothing while loading or if it fails', async () => {
    mockPending('/api/clock')
    const { container } = setup(<ClockPanel folder="/data" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows error if suggestion fails', async () => {
    mockGet('/api/clock', makeClockState({ offset_s: 1.5, has_track: true }))
    mockError('/api/clock/suggest', 500, 'failed to suggest')

    const { user } = setup(<ClockPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'suggest' }))
    expect(await screen.findByText('failed to suggest')).toBeInTheDocument()
  })

  it('renders current offset and handles nudge and set', async () => {
    mockGet('/api/clock', makeClockState({ offset_s: 1.5 }))
    const seen = recordRequests('/api/clock')

    const { user } = setup(<ClockPanel folder="/data" />)

    // shows current offset
    expect(await screen.findByText(/1\.5 s/)).toBeInTheDocument()

    // click +10 s nudge
    await user.click(screen.getByRole('button', { name: '+10 s' }))

    // verify post request body is offset_s + 10 = 11.5
    // seen[0] is GET /api/clock, seen[1] is POST
    expect(seen.find(req => req.method === 'POST')).toMatchObject({ method: 'POST', body: { offset_seconds: 11.5, folder: '/data' } })

    // type specific offset and set
    const input = screen.getByPlaceholderText('seconds')
    await user.clear(input)
    await user.type(input, '-3.5')
    await user.click(screen.getByRole('button', { name: 'set' }))

    expect(seen.filter(req => req.method === 'POST')[1]).toMatchObject({ method: 'POST', body: { offset_seconds: -3.5, folder: '/data' } })
  })

  it('requests and applies clock suggestions', async () => {
    mockGet('/api/clock', makeClockState({ offset_s: 0, has_track: true }))
    mockGet('/api/clock/suggest', { current: 0, suggestions: [{ offset_s: 14.5, votes: 3, confidence: 0.95, score: 5 }] })
    const seen = recordRequests('/api/clock')

    const { user } = setup(<ClockPanel folder="/data" />)
    await screen.findByRole('button', { name: 'suggest' })

    await user.click(screen.getByRole('button', { name: 'suggest' }))

    // See the suggestion rendered
    expect(await screen.findByText('+14.5 s')).toBeInTheDocument()
    expect(screen.getByText(/95% sure/)).toBeInTheDocument()

    // Use suggestion
    await user.click(screen.getByRole('button', { name: 'use' }))
    expect(seen.some(req => req.method === 'POST' && typeof req.body === 'object' && req.body !== null && 'offset_seconds' in req.body && (req.body as any).offset_seconds === 14.5)).toBe(true)
  })

  it('disables suggest button if track is missing', async () => {
    mockGet('/api/clock', makeClockState({ has_track: false }))
    setup(<ClockPanel folder="/data" />)
    expect(await screen.findByRole('button', { name: 'suggest' })).toBeDisabled()
    expect(screen.getByText(/Add the race track/)).toBeInTheDocument()
  })

  it('has no accessibility violations once loaded', async () => {
    mockGet('/api/clock', makeClockState({ offset_s: 0, has_track: true }))
    const { container } = setup(<ClockPanel folder="/data" />)
    await screen.findByRole('button', { name: 'suggest' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
