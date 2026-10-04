import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import GapView from '../../src/components/GapView'
import { screen, setup, waitFor } from '../utils/render'
import { makeGap, makeGapClip } from '../utils/factories'
import { mockGet, mockPost, recordRequests } from '../utils/api'
import { http, HttpResponse } from 'msw'
import { server } from '../utils/server'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

const settings = (o = {}) => ({ kind: null, mode: null, seconds: null, must: false, ...o })

describe('GapView', () => {
  it('says so for a gap that is not there', async () => {
    mockGet('/api/gaps', { gaps: [makeGap()] })
    setup(<GapView folder="/data" gap="G09" />)
    expect(await screen.findByText(/No gap G09/)).toBeInTheDocument()
  })

  it('shows the gap, its state, a preview of the ready clip and what the script does over it', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ settings: settings(), script: [{ n: 4, type: 'vo', text: 'Hours of nothing but road.', seconds: null, kind: null }], clips: [makeGapClip({ exists: true, seconds: 14 })] })] })
    setup(<GapView folder="/data" gap="G01" />)
    expect(await screen.findByRole('heading', { name: /Gap G01/ })).toBeInTheDocument()
    expect(screen.getByLabelText('State')).toHaveTextContent('ready · 2D · 14 s'); expect(document.querySelector('video')).not.toBeNull()
    expect(screen.getByText('Hours of nothing but road.')).toBeInTheDocument(); expect(screen.getByText(/Narration you want spoken inside this gap/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Notes for this gap')).toBeInTheDocument())
  })

  it('says when the script does not use the gap, and that must-use adds it', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ settings: settings({ must: true }), script: [] })] })
    setup(<GapView folder="/data" gap="G01" />)
    expect(await screen.findByText(/does not use this gap \(it is marked must-use, so the plan adds it\)/)).toBeInTheDocument()
  })

  it('saves the kind, the length mode with its seconds and must-use as they are changed', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ settings: settings() })], flyover: { available: true, note: '' } }); const seen = recordRequests('/api/gaps/settings'); mockPost('/api/gaps/settings', settings())
    const { user } = setup(<GapView folder="/data" gap="G01" />)
    await user.selectOptions(await screen.findByLabelText('Drawn as'), 'flyover'); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ folder: '/data', gap: 'G01', kind: 'flyover' }))
    expect(screen.getByLabelText('Length in seconds')).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Length'), 'min'); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ gap: 'G01', mode: 'min', seconds: 14 }))
    await user.click(screen.getByLabelText('Must be used in the film')); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ must: true }))
  })

  it('edits the seconds of a length that is set, saving when the box is left', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ settings: settings({ mode: 'set', seconds: 10 }) })] }); const seen = recordRequests('/api/gaps/settings'); mockPost('/api/gaps/settings', settings({ mode: 'set', seconds: 12 }))
    const { user } = setup(<GapView folder="/data" gap="G01" />)
    const box = await screen.findByLabelText('Length in seconds'); expect(box).toHaveValue(10); expect(screen.getByText(/exactly this long/)).toBeInTheDocument()
    await user.clear(box); await user.type(box, '12{Enter}'); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ seconds: 12 }))
  })

  it('generates the clip in the kind and at the length you set', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ settings: settings({ kind: 'flyover', mode: 'min', seconds: 9 }) })], flyover: { available: true, note: '' } })
    const plan = recordRequests('/api/gaps/clip'); mockPost('/api/gaps/clip', makeGapClip({ kind: 'flyover' })); const render = recordRequests('/api/gaps/render'); mockPost('/api/gaps/render', { started: true })
    const { user } = setup(<GapView folder="/data" gap="G01" />)
    await user.click(await screen.findByRole('button', { name: 'Generate 3D flyover' }))
    await waitFor(() => expect(render.length).toBeGreaterThan(0)); expect(plan.at(-1)?.body).toMatchObject({ gap: 'G01', seconds: 9, kind: 'flyover' })
  })

  it('shows the stop facts on the page of a gap that is a stop, and can take the stop out of the video', async () => {
    mockGet('/api/gaps', { gaps: [makeGap({ id: 'G05', stop: { key: 'k1', arrived: 1_771_600_000, left: 1_771_603_120, stopped_s: 3120, radius_m: 60, km: 114.9, lat: 50, lon: 5, pad_s: 600 } })] })
    const seen = recordRequests('/api/stops'); server.use(http.post('/api/stops', () => HttpResponse.json({ tracks: [], pois: [], runs: 0, merged: null })))
    const { user } = setup(<GapView folder="/data" gap="G05" tz="UTC" />); expect(await screen.findByRole('heading', { name: /Stop G05/ })).toBeInTheDocument(); expect(screen.getByText('The stop')).toBeInTheDocument()
    expect(screen.getByText(/52 min, within 60 m/)).toBeInTheDocument(); expect(screen.getByText(/starts 10 min before the stop and ends 10 min after it/)).toBeInTheDocument(); expect(screen.getByText(/km 114.9 of the run/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Take this stop out of the video' })); await waitFor(() => expect(seen.filter(r => r.method === 'POST')).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', key: 'k1', add: false })
  })
})
