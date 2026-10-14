import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from '@testing-library/react'
import { api } from '../../src/api'
import { axe } from 'vitest-axe'
import { mockGet, mockPending, mockError, mockPost, recordRequests } from '../utils/api'
import { screen, setup } from '../utils/render'
import { stubBrowserApis } from '../utils/media'
import FilmPreview from '../../src/components/FilmPreview'
import { makeFilmState } from '../utils/factories'

stubBrowserApis()

it('renders empty while loading', () => {
  mockPending('/api/film')
  const { container } = setup(<FilmPreview folder="/f" />)
  expect(container.firstChild).toBeNull() // renders nothing while waiting
})

it('renders noplan state', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'noplan' }))
  const { findByText } = setup(<FilmPreview folder="/f" />)
  expect(await findByText('Film preview')).toBeInTheDocument()
  expect(await findByText('Make a plan first.')).toBeInTheDocument()
})

it('shows start button when not ready', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'none' }))
  const { user, findByRole } = setup(<FilmPreview folder="/f" />)
  const btn = await findByRole('button', { name: 'Render preview' })
  expect(btn).toBeInTheDocument()

  const reqs = recordRequests('/api/film/start')
  mockPost('/api/film/start', { started: true })
  await user.click(btn)

  await vi.waitFor(() => expect(reqs).toHaveLength(1))
  expect(reqs[0]).toMatchObject({ method: 'POST', body: { folder: '/f', force: false } })
})

it('shows progress while building', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'rendering', frames_done: 25, frames_total: 100, length_s: 4 }))
  const { findByText } = setup(<FilmPreview folder="/f" />)
  expect(await findByText('rendering 25% (1 of 4 s)')).toBeInTheDocument()
})

it('renders the player when ready', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'done' }))
  const { findByRole } = setup(<FilmPreview folder="/f" />)
  // jsdom won't load media natively but the video element should be present
  expect(await findByRole('button', { name: 'Render again' })).toBeInTheDocument()
})

it('handles stop click during build', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'rendering' }))
  const { user, findByRole, findByText } = setup(<FilmPreview folder="/f" />)

  const reqs = recordRequests('/api/film/stop')
  mockPost('/api/film/stop', { ok: true })
  const btn = await findByRole('button', { name: 'stop' })
  await user.click(btn)

  await vi.waitFor(() => expect(reqs).toHaveLength(1))
  expect(reqs[0]).toMatchObject({ method: 'POST', body: { folder: '/f' } })
})

it('has no accessibility violations', async () => {
  mockGet('/api/film', () => makeFilmState({ state: 'done' }))
  const { container, findByRole } = setup(<FilmPreview folder="/f" />)
  await findByRole('button', { name: 'Render again' }) // Wait for load
  expect(await axe(container)).toHaveNoViolations()
})


// hls.js needs MediaSource, which jsdom does not have: this stand-in records how the player is wired.
const hls = vi.hoisted(() => ({ supported: true, instances: [] as Array<{ cfg: unknown; src?: string; media?: HTMLVideoElement; destroyed: boolean; fire: (d: { fatal: boolean; details: string }) => void }> }))
vi.mock('hls.js', () => {
  class Hls {
    static Events = { ERROR: 'hlsError' }
    static isSupported = () => hls.supported
    h: ((e: string, d: { fatal: boolean; details: string }) => void) | null = null
    rec: (typeof hls.instances)[number]
    constructor(cfg: unknown) { this.rec = { cfg, destroyed: false, fire: d => act(() => this.h?.('hlsError', d)) }; hls.instances.push(this.rec) }
    loadSource(u: string) { this.rec.src = u }
    attachMedia(v: HTMLVideoElement) { this.rec.media = v }
    on(_e: string, f: (e: string, d: { fatal: boolean; details: string }) => void) { this.h = f }
    destroy() { this.rec.destroyed = true }
  }
  return { default: Hls }
})

describe('FilmPreview while the film is being made', () => {
  beforeEach(() => { hls.supported = true; hls.instances.length = 0 })
  const live = (o = {}) => mockGet('/api/film', () => makeFilmState({ state: 'rendering', key: 'k1', frames_done: 60, frames_total: 100, length_s: 4, ...o }))

  it('starts playing the stream once more than two seconds are made', async () => {
    live(); const { container } = setup(<FilmPreview folder="/f" />)
    await vi.waitFor(() => expect(hls.instances).toHaveLength(1))
    expect(hls.instances[0].src).toBe(api.filmUrl('/f')); expect(hls.instances[0].media).toBe(container.querySelector('video'))
    expect(screen.getByRole('button', { name: 'Previous frame' })).toBeInTheDocument()
  })

  it('shows no player before that, only a placeholder', async () => {
    live({ frames_done: 50 }); const { container } = setup(<FilmPreview folder="/f" />)
    await screen.findByText(/rendering 50%/); expect(container.querySelector('video')).toBeNull(); expect(hls.instances).toEqual([])
  })

  it('plays a finished preview too, and starts again from the beginning for a new plan', async () => {
    let key = 'k1'; mockGet('/api/film', () => makeFilmState({ state: 'done', key, frames_done: 100, frames_total: 100 }))
    setup(<FilmPreview folder="/f" />); await vi.waitFor(() => expect(hls.instances).toHaveLength(1))
    key = 'k2'; await vi.waitFor(() => expect(hls.instances).toHaveLength(2), { timeout: 4000 }); expect(hls.instances[0].destroyed).toBe(true)
  })

  it('shows a fatal player error and ignores one it recovers from', async () => {
    live(); setup(<FilmPreview folder="/f" />); await vi.waitFor(() => expect(hls.instances).toHaveLength(1))
    hls.instances[0].fire({ fatal: false, details: 'bufferStalled' }); expect(screen.queryByText(/player:/)).not.toBeInTheDocument()
    hls.instances[0].fire({ fatal: true, details: 'manifestLoadError' }); expect(await screen.findByText('player: manifestLoadError')).toBeInTheDocument()
  })

  it('lets the browser play the stream itself when it can (Safari)', async () => {
    hls.supported = false; vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('maybe')
    live(); const { container } = setup(<FilmPreview folder="/f" />)
    await vi.waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).src).toContain('/api/film/index.m3u8')); expect(hls.instances).toEqual([])
  })

  it('does nothing for a browser that cannot play the stream at all', async () => {
    hls.supported = false; vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('')
    live(); const { container } = setup(<FilmPreview folder="/f" />)
    await screen.findByText(/rendering 60%/); expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src')).toBeNull()
  })

  it('stops the stream when the preview is closed', async () => {
    live(); const { unmount } = setup(<FilmPreview folder="/f" />); await vi.waitFor(() => expect(hls.instances).toHaveLength(1))
    unmount(); expect(hls.instances[0].destroyed).toBe(true)
  })
})

describe('FilmPreview messages', () => {
  it('says the sound is being prepared before the pictures start', async () => {
    mockGet('/api/film', () => makeFilmState({ state: 'audio' })); setup(<FilmPreview folder="/f" />)
    expect(await screen.findByText('preparing the sound…')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'stop' })).toBeInTheDocument()
  })

  it('shows the reason a render failed, or a plain "failed"', async () => {
    mockGet('/api/film', () => makeFilmState({ state: 'error', error: 'ffmpeg died' })); const { unmount } = setup(<FilmPreview folder="/f" />)
    expect(await screen.findByText('ffmpeg died')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Render preview' })).toBeInTheDocument(); unmount()
    mockGet('/api/film', () => makeFilmState({ state: 'error' })); setup(<FilmPreview folder="/f" />); expect(await screen.findByText('failed')).toBeInTheDocument()
  })

  it('names the clips that have no proxy video yet', async () => {
    mockGet('/api/film', () => makeFilmState({ state: 'none', placeholders: ['CAM_20260221120007_0019_D', 'CAM_20260221130000_0020_D'] })); setup(<FilmPreview folder="/f" />)
    expect(await screen.findByText(/2 clip\(s\) have no proxy video yet and show as dark cards: 07_0019_D, 00_0020_D\./)).toBeInTheDocument()
  })

  it('asks for a new render over a finished one, and for a first one without forcing', async () => {
    const seen = recordRequests('/api/film/start')
    mockGet('/api/film', () => makeFilmState({ state: 'done', frames_done: 0 })); const first = setup(<FilmPreview folder="/f" />)
    await first.user.click(await screen.findByRole('button', { name: 'Render again' })); first.unmount()
    mockGet('/api/film', () => makeFilmState({ state: 'none' })); const second = setup(<FilmPreview folder="/f" />)
    await second.user.click(await screen.findByRole('button', { name: 'Render preview' }))
    await vi.waitFor(() => expect(seen).toHaveLength(2)); expect(seen.map(s => s.body)).toEqual([{ folder: '/f', force: true }, { folder: '/f', force: false }])
  })

  it('shows 0% before the number of frames is known', async () => {
    mockGet('/api/film', () => makeFilmState({ state: 'rendering', frames_done: 5 })); setup(<FilmPreview folder="/f" />)
    expect(await screen.findByText('rendering 0% (0 of 0 s)')).toBeInTheDocument()
  })
})
