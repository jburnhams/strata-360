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

  it('renders places when covered is true', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      places: {
        covered: true,
        summary: { text: 'A nice road', places: [] },
        points: [
          { label: 'p1', lat: 10, lon: 20, address: { road: 'Start St' }, nearby: [{ name: 'Cafe', kind: 'amenity=cafe', distance_m: 10 }] },
          { label: 'p2', lat: 10, lon: 21, address: { road: 'End St' }, nearby: [] }
        ]
      }
    }))
    const { findByText } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(await findByText('A nice road')).toBeInTheDocument()
    expect(await findByText('Start St → End St')).toBeInTheDocument()
    expect(await findByText('Cafe')).toBeInTheDocument()
    expect(await findByText('10 m')).toBeInTheDocument()
    expect(await findByText('open in OpenStreetMap')).toHaveAttribute('href', 'https://www.openstreetmap.org/?mlat=10&mlon=20#map=16/10/20')
  })

  it('renders places when covered is false', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      places: { covered: false, note: 'Off road', points: [] }
    }))
    const { findByText } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(await findByText('Off road')).toBeInTheDocument()
  })

  it('renders different sound classes based on hints', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      sounds: {
        seconds: { wind: 1, music: 1, traffic: 1, unknown: 1 },
        hints: { wind: ['avoid', 0], music: ['voice', 0], traffic: ['energy', 0] },
        windows: [
          { t0: 0, t1: 1, cats: { wind: 1 }, top: [] }, // avoid -> red
          { t0: 1, t1: 2, cats: { music: 1 }, top: [] }, // voice -> green
          { t0: 2, t1: 3, cats: { traffic: 1 }, top: [] }, // energy -> green
          { t0: 3, t1: 4, cats: { unknown: 1 }, top: [] }, // top exists -> blue
          { t0: 4, t1: 5, cats: {}, top: [] } // no top -> stone
        ]
      }
    }))
    const { findByTitle } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(await findByTitle('0:00–0:01: wind 1.00')).toHaveClass('bg-red-400')
    expect(await findByTitle('0:01–0:02: music 1.00')).toHaveClass('bg-emerald-500')
    expect(await findByTitle('0:02–0:03: traffic 1.00')).toHaveClass('bg-emerald-500')
    expect(await findByTitle('0:03–0:04: unknown 1.00')).toHaveClass('bg-sky-400')
    expect(await findByTitle('0:04: nothing but speech')).toHaveClass('bg-stone-300')
  })

  it('renders "other" when who is other in transcript', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      transcript: [{ si: 1, t0: 0, t1: 1, text: 'hi', text_en: 'hi', lang: 'en', flagged: false, who: 'other', words: [] }]
    }))
    const { findByText } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(await findByText('other')).toBeInTheDocument()
  })

  it('allows changing the transcript language mode', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      transcript: [{ si: 1, t0: 0, t1: 1, text: 'bonjour', text_en: 'hello', lang: 'fr', flagged: false, who: 'wearer', words: [] }]
    }))
    const { findByRole, findByText, queryByText } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)

    // Default mode is 'translated'
    expect(await findByText('hello')).toBeInTheDocument()
    expect(queryByText('bonjour')).not.toBeInTheDocument()

    const modeSelect = await findByRole('combobox', { name: '' }) // no label for the select
    await userEvent.selectOptions(modeSelect, 'original')
    expect(await findByText('bonjour')).toBeInTheDocument()
    expect(queryByText('hello')).not.toBeInTheDocument()

    await userEvent.selectOptions(modeSelect, 'both')
    expect(await findByText('hello')).toBeInTheDocument()
    expect(await findByText('bonjour')).toBeInTheDocument()
  })

  it('renders missing thumbnail and empty transcript states', async () => {
    mockGet('/api/pointcams', makePointCams())
    mockGet('/api/clip', makeClipDetail({
      thumb: null,
      transcript: []
    }))
    const { findByText } = setup(<ClipView folder="f" clip="c1" tz="UTC" />)
    expect(await findByText('no thumbnail yet')).toBeInTheDocument()
    expect(await findByText('No speech recognised.')).toBeInTheDocument()
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
