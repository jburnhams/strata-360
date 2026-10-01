import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import WhoPanel from '../../src/components/WhoPanel'
import { screen, setup } from '../utils/render'
import { makeWhoState } from '../utils/factories'
import { mockGet, mockError, recordRequests, mockPending } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('WhoPanel', () => {
  it('renders nothing while loading', () => {
    mockPending('/api/who')
    const { container } = setup(<WhoPanel folder="/data" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders reason when not ready', async () => {
    mockGet('/api/who', makeWhoState({ ready: false, reason: 'extracting faces' }))
    setup(<WhoPanel folder="/data" />)
    expect(await screen.findByText(/extracting faces/)).toBeInTheDocument()
  })

  it('shows unchosen state when ready but profile not selected', async () => {
    mockGet('/api/who', makeWhoState({
      ready: true,
      profile: false,
      sheet: true,
      suggested: { clusters: [1], confident: true, why: 'often talking' },
      clusters: [{ cluster: 1, n: 5, clips: 2, rear_fraction: 0.5, median_size_px: 100 }, { cluster: 2, n: 3, clips: 1, rear_fraction: 0.1, median_size_px: 50 }]
    }))
    setup(<WhoPanel folder="/data" />)

    // Panel title
    expect(await screen.findByText('Which face is you')).toBeInTheDocument()

    // Suggestion is rendered
    expect(screen.getByText(/often talking/)).toBeInTheDocument()

    // Inputs are rendered
    expect(screen.getByLabelText(/#1/)).toBeInTheDocument()
    expect(screen.getByLabelText(/#2/)).toBeInTheDocument()

    // By default suggested is selected, so #1 should be checked
    expect(screen.getByLabelText(/#1/)).toBeChecked()
    expect(screen.getByLabelText(/#2/)).not.toBeChecked()
  })

  it('selects clusters and saves them', async () => {
    mockGet('/api/who', makeWhoState({
      ready: true,
      profile: false,
      sheet: true,
      suggested: { clusters: [1], confident: true, why: 'often talking' },
      clusters: [{ cluster: 1, n: 5, clips: 2, rear_fraction: 0.5, median_size_px: 100 }, { cluster: 2, n: 3, clips: 1, rear_fraction: 0.1, median_size_px: 50 }]
    }))
    const seen = recordRequests('/api/who')

    const { user } = setup(<WhoPanel folder="/data" />)
    await screen.findByLabelText(/#2/)

    // Select cluster 2 as well
    await user.click(screen.getByLabelText(/#2/))
    expect(screen.getByLabelText(/#2/)).toBeChecked()

    // Save
    await user.click(screen.getByRole('button', { name: /This is me/ }))

    // Expect post
    expect(seen.find(req => req.method === 'POST')).toMatchObject({ method: 'POST', body: { folder: '/data', me: [1, 2] } })
  })

  it('can toggle face view when a profile is already selected', async () => {
    mockGet('/api/who', makeWhoState({
      ready: true,
      profile: true,
      sheet: true,
      clusters: [{ cluster: 3, n: 5, clips: 2, rear_fraction: 0.5, median_size_px: 100 }]
    }))

    const { user } = setup(<WhoPanel folder="/data" />)

    // Initially hidden
    expect(await screen.findByText('Which face is you')).toBeInTheDocument()
    expect(screen.queryByLabelText(/#3/)).not.toBeInTheDocument()

    // Show faces
    await user.click(screen.getByRole('button', { name: 'change' }))
    expect(await screen.findByLabelText(/#3/)).toBeInTheDocument()

    // Hide faces
    await user.click(screen.getByRole('button', { name: 'hide' }))
    expect(screen.queryByLabelText(/#3/)).not.toBeInTheDocument()
  })

  it('shows error if saving fails', async () => {
    mockGet('/api/who', makeWhoState({
      ready: true,
      profile: false,
      sheet: true,
      suggested: { clusters: [1], confident: true, why: 'often talking' },
      clusters: [{ cluster: 1, n: 5, clips: 2, rear_fraction: 0.5, median_size_px: 100 }]
    }))
    mockError('/api/who', 500, 'failed to save who', 'post')
    const { user } = setup(<WhoPanel folder="/data" />)

    await user.click(await screen.findByRole('button', { name: /This is me/ }))
    expect(await screen.findByText('failed to save who')).toBeInTheDocument()
  })

  it('has no accessibility violations once loaded', async () => {
    mockGet('/api/who', makeWhoState({
      ready: true,
      profile: false,
      sheet: true,
      suggested: { clusters: [1], confident: true, why: 'often talking' },
      clusters: [{ cluster: 1, n: 5, clips: 2, rear_fraction: 0.5, median_size_px: 100 }]
    }))
    const { container } = setup(<WhoPanel folder="/data" />)
    await screen.findByText('Which face is you')
    expect(await axe(container)).toHaveNoViolations()
  })
})
