import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import ProjectProgress from '../../src/components/ProjectProgress'
import { mockGet, mockPending, recordRequests } from '../utils/api'
import { makeProgress } from '../utils/factories'
import { act, screen, setup } from '../utils/render'

const props = { folder: '/data' }
const mount = () => setup(<ProjectProgress {...props} />, undefined)

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers() })

describe('ProjectProgress', () => {
  it('shows a skeleton while loading', () => {
    mockPending('/api/progress')
    mount()
    expect(screen.getByRole('region', { name: 'Loading Progress' })).toBeInTheDocument()
  })

  it('displays the complete state', async () => {
    mockGet('/api/progress', makeProgress({ state: 'complete', percent: 100, clips: 5, footage_gb: 1.2, eta_s: 0 }))
    mount()
    expect(await screen.findByText('Complete')).toBeInTheDocument()
    expect(screen.getByText(/5 clips/)).toBeInTheDocument()
    expect(screen.getByText(/1.2 GB/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to results and export' })).toBeInTheDocument()
  })

  it('displays stages with workers running and logs', async () => {
    mockGet('/api/progress', makeProgress({
      state: 'processing',
      percent: 50,
      eta_s: 300,
      stages: [
        { name: 'download', done: 5, total: 10, note: 'getting files', seconds_per_clip: null, eta_s: null },
        { name: 'transcode', done: 2, total: 10, note: 'converting', seconds_per_clip: null, eta_s: null, running: [{ clip: 'c1234_D', pid: 999 }] }
      ]
    }))
    mockGet('/api/log', { lines: ['Started download', 'Processing transcode'] })
    mount()
    expect(await screen.findByText('Processing…')).toBeInTheDocument()
    expect(screen.getByText(/about 5 min left/)).toBeInTheDocument()
    expect(screen.getByText('download')).toBeInTheDocument()
    expect(screen.getByText('5/10')).toBeInTheDocument()
    expect(screen.getByText('transcode')).toBeInTheDocument()
    expect(screen.getByText('2/10')).toBeInTheDocument()
    expect(screen.getByText(/clip 1234/)).toBeInTheDocument() // _D stripped
    await vi.waitFor(() => expect(screen.getByText(/Started download[\s\S]*Processing transcode/)).toBeInTheDocument())
  })

  it('displays needs_input and corresponding text', async () => {
    mockGet('/api/progress', makeProgress({ state: 'needs_input', needs: ['wearer_profile', 'camera_clock', 'unknown_need'] }))
    mount()
    expect(await screen.findByText('Waiting for you')).toBeInTheDocument()
    expect(screen.getByText(/To do: choose which face is you, confirm the camera clock, unknown_need/)).toBeInTheDocument()
  })

  it('starts processing when no workers are running but there are runnable items', async () => {
    mockGet('/api/progress', makeProgress({ state: 'new', workers: 0, runnable: 3 }))
    const seen = recordRequests('/api/run')
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Start processing' }))
    expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ folder: '/data' })
  })

  it('adds a worker when workers exist and can add more', async () => {
    mockGet('/api/progress', makeProgress({ state: 'processing', workers: 1, can_add_worker: true, runnable: 5 }))
    const seen = recordRequests('/api/run')
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Add a worker (5 items waiting)' }))
    expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ folder: '/data' })
  })

  it('explains why a worker cannot be added when applicable', async () => {
    mockGet('/api/progress', makeProgress({ state: 'processing', workers: 2, can_add_worker: false, add_worker_reason: 'out of memory', runnable: 1 }))
    mount()
    expect(await screen.findByText(/no more for now: out of memory/)).toBeInTheDocument()
  })

  it('stops all processing when requested', async () => {
    mockGet('/api/progress', makeProgress({ state: 'processing', workers: 1, runnable: 0 }))
    const seen = recordRequests('/api/stop')
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Stop all' }))
    expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ folder: '/data' })
  })

  it('stops a specific worker', async () => {
    mockGet('/api/progress', makeProgress({
      state: 'processing',
      stages: [{ name: 'test_stage', done: 0, total: 1, note: '', seconds_per_clip: null, eta_s: null, running: [{ clip: '1234_D', pid: 123 }] }]
    }))
    const seen = recordRequests('/api/stop')
    const { user } = mount()
    await user.click(await screen.findByTitle('stop this worker (pid 123)'))
    expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ folder: '/data', pid: 123 })
  })

  it('opens and closes the redo dialog', async () => {
    mockGet('/api/progress', makeProgress({ state: 'complete' }))
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Reprocess…' }))
    expect(await screen.findByText('Reprocess')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Reprocess')).not.toBeInTheDocument()
  })

  it('opens redo dialog for a specific stage', async () => {
    mockGet('/api/progress', makeProgress({
      state: 'complete',
      stages: [{ name: 'align', done: 10, total: 10, note: '', seconds_per_clip: null, eta_s: null }]
    }))
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'redo' }))
    expect(await screen.findByText('Reprocess: align')).toBeInTheDocument()
  })

  it('has no accessibility violations once loaded', async () => {
    mockGet('/api/progress', makeProgress({ state: 'processing', percent: 20, workers: 1, can_add_worker: false, runnable: 0, needs: ['wearer_profile'] }))
    const { container } = mount()
    await screen.findByText('Processing…')
    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('ProjectProgress coverage', () => {
  it('lists the decisions blocked by missing data', async () => {
    mockGet('/api/progress', makeProgress({ state: 'processing' }))
    mockGet('/api/log', { lines: [] })
    mockGet('/api/coverage', { clips: 2, stages: ['motion'], totals: { motion: 1 }, blocked: { 'steadiness, usable footage': ['a'] }, missing: [{ clip: 'b', stage: 'motion', state: 'missing' }], complete: false })
    mount()
    expect(await screen.findByText(/Data missing: 1 item · blocks 1 decision/)).toBeInTheDocument()
  })
})
