import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import GapsPanel from '../../src/components/GapsPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeGap, makeGapClip } from '../utils/factories'
import { mockGet, mockPost, mockDelete, mockError, recordRequests } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('GapsPanel', () => {
  it('says so when there are no gaps', async () => {
    mockGet('/api/gaps', { gaps: [] })
    setup(<GapsPanel folder="/data" />)
    expect(await screen.findByText(/No gaps of 20 minutes or more/)).toBeInTheDocument()
  })

  it('lists each gap with its times, distance and default length', async () => {
    mockGet('/api/gaps', { gaps: [makeGap(), makeGap({ id: 'G02', local_start: 'Thu 19 Feb 21:47', default_seconds: 20 })] })
    setup(<GapsPanel folder="/data" />)
    expect(await screen.findByText('G01')).toBeInTheDocument()
    expect(screen.getByText(/Thu 19 Feb 18:17/)).toBeInTheDocument()
    expect(screen.getAllByText(/km 2.5–27/)).toHaveLength(2)
    expect(screen.getByLabelText('Seconds for G01')).toHaveValue(14)
    expect(screen.getByLabelText('Seconds for G02')).toHaveValue(20)
    expect(screen.getAllByRole('button', { name: 'Generate map clip' })).toHaveLength(2)
  })

  it('plans the clip with the chosen length, then starts rendering it', async () => {
    mockGet('/api/gaps', { gaps: [makeGap()] })
    const plan = recordRequests('/api/gaps/clip'); mockPost('/api/gaps/clip', makeGapClip({ seconds: 25 }))
    const render = recordRequests('/api/gaps/render'); mockPost('/api/gaps/render', { started: true })
    const { user } = setup(<GapsPanel folder="/data" />)
    const box = await screen.findByLabelText('Seconds for G01')
    await user.clear(box); await user.type(box, '25')
    await user.click(screen.getByRole('button', { name: 'Generate map clip' }))
    await waitFor(() => expect(render).toHaveLength(1))
    expect(plan[0].body).toEqual({ folder: '/data', gap: 'G01', seconds: 25, kind: 'map' })
    expect(render[0].body).toEqual({ folder: '/data', id: 'G01' })
  })

  it('plans a 3D flyover when that kind is chosen', async () => {
    mockGet('/api/gaps', { gaps: [makeGap()], flyover: { available: true, note: '' } })
    const plan = recordRequests('/api/gaps/clip'); mockPost('/api/gaps/clip', makeGapClip({ kind: 'flyover', size: '3840x2160' }))
    const render = recordRequests('/api/gaps/render'); mockPost('/api/gaps/render', { started: true })
    const { user } = setup(<GapsPanel folder="/data" />)
    await user.selectOptions(await screen.findByLabelText('Kind for G01'), 'flyover')
    await user.click(screen.getByRole('button', { name: 'Generate 3D flyover' }))
    await waitFor(() => expect(render).toHaveLength(1))
    expect(plan[0].body).toEqual({ folder: '/data', gap: 'G01', seconds: 14, kind: 'flyover' })
  })

  it('offers the 3D flyover but not as a choice when the renderer is not installed', async () => {
    mockGet('/api/gaps', { gaps: [makeGap()], flyover: { available: false, note: 'mbgl-render is not installed' } })
    setup(<GapsPanel folder="/data" />)
    const opt = await screen.findByRole('option', { name: /3D flyover.*not installed/ })
    expect(opt).toBeDisabled(); expect(opt).toHaveAttribute('title', 'mbgl-render is not installed')
  })

  it('shows the kind of a planned clip, and its 3D label once rendered', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ clips: [makeGapClip({ kind: 'flyover', exists: true, status: 'ready' })] })] })
    const { user } = setup(<GapsPanel folder="/data" />)
    expect(await screen.findByLabelText('Kind for G01')).toHaveValue('flyover')
    expect(screen.getByText(/ready · 3D · 14 s/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Watch' }))
    expect(screen.getByLabelText('G01 flyover')).toBeInTheDocument()
  })

  it('shows a render in progress and does not allow starting another', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ clips: [makeGapClip({ rendering: true, progress: 'G01: 60/420 frames' })] })] })
    setup(<GapsPanel folder="/data" />)
    expect(await screen.findByText('G01: 60/420 frames')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate map clip' })).toBeDisabled()
    expect(screen.getByLabelText('Kind for G01')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Remove G01 clip' })).not.toBeInTheDocument()
  })

  it('shows why the last render failed', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ clips: [makeGapClip({ error: 'strata360.overlay.tiles.MissingKey: the map style tf-landscape needs a key' })] })] })
    setup(<GapsPanel folder="/data" />)
    expect(await screen.findByLabelText('G01 state')).toHaveTextContent('failed: strata360.overlay.tiles.MissingKey')
  })

  it('plays a rendered clip and can remove it', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ clips: [makeGapClip({ exists: true, status: 'ready' })] })] })
    const del = recordRequests('/api/gaps/clip'); mockDelete('/api/gaps/clip', { removed: true })
    const { user } = setup(<GapsPanel folder="/data" />)
    expect(await screen.findByText(/ready · 14 s for 3.5 h \(x900\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Watch' }))
    expect(screen.getByLabelText('G01 map clip')).toHaveAttribute('src', '/api/gaps/video?folder=%2Fdata&id=G01')
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove G01 clip' }))
    await waitFor(() => expect(del).toHaveLength(1))
    expect(del[0].url.searchParams.get('id')).toBe('G01')
  })

  it('shows the reason when planning fails', async () => {
    mockGet('/api/gaps', { gaps: [makeGap()] }); mockError('/api/gaps/clip', 400, 'a clip shorter than 2 s is not useful', 'post')
    const { user } = setup(<GapsPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Generate map clip' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('a clip shorter than 2 s is not useful')
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ clips: [makeGapClip({ exists: true })] })] })
    const { container } = setup(<GapsPanel folder="/data" />)
    await screen.findByText('G01')
    expect(await axe(container)).toHaveNoViolations()
  })
})
