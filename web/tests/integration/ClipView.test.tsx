import { expect, it, describe, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import ClipView from '../../src/components/ClipView'
import { setup } from '../utils/render'
import { mockGet, mockPost, mockError, recordRequests } from '../utils/api'
import { makeClipDetail, makePointCams } from '../utils/factories'

vi.mock('../../src/components/ClipPlayer', () => ({
  default: () => <div data-testid="clip-player">ClipPlayer</div>
}))

vi.mock('../../src/components/TrackMap', () => ({
  default: () => <div data-testid="track-map">TrackMap</div>
}))

describe('ClipView', () => {
  it('shows loading skeletons initially', () => {
    mockGet('/api/pointcams', makePointCams())
    const { getByRole, container } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(getByRole('region', { name: 'Loading When and where' })).toBeInTheDocument()
    expect(getByRole('region', { name: 'Loading Motion and picture' })).toBeInTheDocument()
    expect(getByRole('region', { name: 'Loading Transcript' })).toBeInTheDocument()
  })

  it('shows an error if clip fetch fails', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockError('/api/clip', 500, 'Failed to fetch clip')
    const { findByText } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(await findByText('Failed to fetch clip')).toBeInTheDocument()
  })

  it('renders clip details when loaded', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      time: { start_utc: '2026-02-22T19:00:00Z', utc_status: 'ok' },
      video: { source_frames: 300, nominal_fps: 30 },
      track_text: 'Track A',
      motion: { steady: 0.9 },
      exposure: { mean_lin_range_stops: 3.2 },
      objects: { objects: [{ id: 1, label: 'dog', lon: 0, lat: 0, deg: 0, seen: [1, 2], word: 'dog', kind: 'named', source: 'vlm', yoloe: 'dog', conf: 0.9, best_t: 1, crop: true }], regions: [], areas: {}, scenery_labels: {}, counts: {}, skipped: null, model: 'Qwen3.5', moments: 4 },
      transcript: [{ si: 1, t0: 0, t1: 1, text: 'hello', text_en: 'hello', lang: 'en', flagged: false, who: 'wearer', words: [] }],
      sounds: { seconds: { voice: 1 }, hints: { voice: ['voice', 0] }, windows: [{ t0: 0, t1: 5, cats: { voice: 0.8 }, top: [] }] }
    }))

    const { findByText, getByText, findByTestId } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)

    expect(await findByTestId('clip-player')).toBeInTheDocument()
    expect(getByText('2026-02-22 19:00:00')).toBeInTheDocument()
    expect(getByText('0:10')).toBeInTheDocument()
    expect(getByText('Track A')).toBeInTheDocument()
    expect(getByText('90%')).toBeInTheDocument()
    expect(getByText('3.2 stops')).toBeInTheDocument()
    expect(getByText('voice 1 s')).toBeInTheDocument()
    expect(getByText('hello')).toBeInTheDocument()
  })

  it('allows hiding objects', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      objects: { objects: [{ id: 1, label: 'dog', lon: 0, lat: 0, deg: 0, seen: [1, 2], word: 'dog', kind: 'named', source: 'vlm', yoloe: 'dog', conf: 0.9, best_t: 1, crop: true }], regions: [], areas: {}, scenery_labels: {}, counts: {}, skipped: null, model: 'Qwen3.5', moments: 4 },
    }))

    const reqs = recordRequests('/api/clip/object/hide')
    mockPost('/api/clip/object/hide', { ok: true })

    const { findByRole } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    const hideBtn = await findByRole('button', { name: 'Hide every dog' })

    await userEvent.click(hideBtn)

    expect(reqs).toHaveLength(1)
    expect(reqs[0].method).toBe('POST')
    expect(reqs[0].body).toEqual({ folder: 'f', label: 'dog', hide: true })
  })

  it('can open the redo dialog', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail())
    const { findByRole, getByRole, queryByRole } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)

    const reprocessBtn = await findByRole('button', { name: 'reprocess…' })
    await userEvent.click(reprocessBtn)

    const cancel = await findByRole('button', { name: 'Cancel' })
    expect(cancel).toBeInTheDocument()

    await userEvent.click(cancel)
    expect(queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })
})
