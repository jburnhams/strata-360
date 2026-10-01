import { describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import RedoDialog from '../../src/components/RedoDialog'
import { mockGet, mockPending, recordRequests } from '../utils/api'
import { makeStateMatrix } from '../utils/factories'
import { act, screen, setup } from '../utils/render'

const props = { folder: '/data', onClose: vi.fn() }
const mount = (extra = {}) => setup(<RedoDialog {...props} {...extra} />, undefined)

describe('RedoDialog', () => {
  it('shows nothing while loading', () => {
    mockPending('/api/state')
    mount()
    expect(screen.queryByText('Reprocess')).not.toBeInTheDocument()
  })

  it('renders the grid with correct title for a full folder redo', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download', 'transcode'],
      clips: { 'CAM_1234_D': { 'download': 'ok', 'transcode': null }, 'CAM_5678_D': { 'download': 'active' } },
      dependents: { 'download': ['transcode'], 'transcode': [] }
    }))
    mount()
    expect(await screen.findByText('Reprocess')).toBeInTheDocument()
    expect(screen.getByText('0 selected')).toBeInTheDocument()
    expect(screen.getByText('1234')).toBeInTheDocument() // "CAM_" and "_D" are stripped, but we just check the number is there
    expect(screen.getByText('5678')).toBeInTheDocument()
    // Verify one of the titles containing the state
    expect(screen.getByTitle('download: active')).toBeInTheDocument()
  })

  it('renders with pre-selected stages when opened for a specific stage', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download', 'transcode'],
      clips: { 'CAM_1': { 'download': 'ok', 'transcode': null }, 'CAM_2': { 'download': 'ok' } },
      dependents: { 'download': ['transcode'], 'transcode': [] }
    }))
    mount({ stage: 'download' })
    expect(await screen.findByText('Reprocess: download')).toBeInTheDocument()
    // It selects download and its dependents (transcode) for each clip, but the initial selection doesn't use `m.stages` flat map,
    // so we need to verify the DOM for what is actually selected. The component uses:
    // `setSel(new Set(Object.keys(x.clips).filter(c => !clip || c === clip).flatMap(c => x.dependents[stage].map(s => \`${c}|${s}\`))))`
    // Looking at the trace, it selects 2 items initially (transcode for CAM_1 and CAM_2).
    expect(screen.getByText('2 selected')).toBeInTheDocument()
  })

  it('filters by clip if clip is provided', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download'],
      clips: { 'CAM_1': { 'download': 'ok' }, 'CAM_2': { 'download': 'ok' } },
      dependents: { 'download': [] }
    }))
    mount({ clip: 'CAM_2' })
    expect(await screen.findByText(/Reprocess.*2/)).toBeInTheDocument() // Check title
    expect(screen.queryByText('1')).not.toBeInTheDocument()
  })

  it('handles "select all" and "select none" buttons', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download'],
      clips: { '1': { 'download': 'ok' }, '2': { 'download': 'ok' } },
      dependents: { 'download': [] }
    }))
    const { user } = mount()
    await screen.findByText('0 selected')
    await user.click(screen.getByRole('button', { name: 'select all' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'select none' }))
    expect(screen.getByText('0 selected')).toBeInTheDocument()
  })

  it('toggles a stage for all clips when clicking stage column header', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download', 'transcode'],
      clips: { '1': { 'download': 'ok' }, '2': { 'download': 'ok' } },
      dependents: { 'download': [], 'transcode': [] }
    }))
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'download' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'download' }))
    expect(screen.getByText('0 selected')).toBeInTheDocument()
  })

  it('toggles a clip for all stages when clicking clip row header', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download', 'transcode'],
      clips: { 'CAM_20230502153045_1': { 'download': 'ok' }, 'CAM_2': { 'download': 'ok' } },
      dependents: { 'download': [], 'transcode': [] }
    }))
    const { user } = mount()
    // It reformats "20230502153045_1" to "02/05 15:30 · 1"
    await user.click(await screen.findByRole('button', { name: '02/05 15:30 · 1' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
  })

  it('handles cascade selection correctly', async () => {
    mockGet('/api/state', makeStateMatrix({
      stages: ['download', 'transcode'],
      clips: { '1': { 'download': 'ok', 'transcode': 'ok' } },
      dependents: { 'download': ['transcode'], 'transcode': [] }
    }))
    const { user } = mount()
    await screen.findByText('0 selected')

    // Toggling download cascades to transcode
    const downloadCheck = screen.getByTitle('download: ok').querySelector('input')!
    await user.click(downloadCheck)
    expect(screen.getByText('2 selected')).toBeInTheDocument()

    // Turn off cascade
    const cascadeCheck = screen.getByLabelText(/also the stages that depend on the one I tick/)
    await user.click(cascadeCheck)

    // Unchecking now only removes download
    await user.click(downloadCheck)
    expect(screen.getByText('1 selected')).toBeInTheDocument()
  })

  it('calls clear API with selected items and closes the dialog', async () => {
    const onClose = vi.fn()
    mockGet('/api/state', makeStateMatrix({
      stages: ['download'],
      clips: { 'c1': { 'download': 'ok' } },
      dependents: { 'download': [] }
    }))
    const seen = recordRequests('/api/clear')
    const { user } = mount({ onClose })

    await screen.findByText('0 selected')
    await user.click(screen.getByRole('button', { name: 'select all' }))
    await user.click(screen.getByRole('button', { name: 'Clear 1 item and reprocess' }))

    expect(seen.find(r => r.method === 'POST')?.body).toMatchObject({ folder: '/data', items: [{ clip: 'c1', stage: 'download' }] })
    expect(onClose).toHaveBeenCalled()
  })

  it('cancels the dialog', async () => {
    const onClose = vi.fn()
    mockGet('/api/state', makeStateMatrix({ stages: ['a'], clips: { '1': {} }, dependents: { 'a': [] } }))
    const { user } = mount({ onClose })
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('has no accessibility violations once loaded', async () => {
    mockGet('/api/state', makeStateMatrix({ stages: ['a'], clips: { '1': {} }, dependents: { 'a': [] } }))
    const { container } = mount()
    await screen.findByText('Reprocess')
    expect(await axe(container)).toHaveNoViolations()
  })
})
