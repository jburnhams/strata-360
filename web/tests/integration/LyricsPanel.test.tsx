import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import LyricsPanel from '../../src/components/LyricsPanel'
import { screen, setup, waitFor } from '../utils/render'
import { makeLyrics, makeLyricPhrase } from '../utils/factories'
import { mockGet, mockPost, mockDelete, recordRequests } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

const found = () => makeLyrics({ exists: true, phrases: 3, sung_s: 12.6, duration_s: 247, language: 'en', phrases_list: [
  makeLyricPhrase(), makeLyricPhrase({ key: '150.0-153.0', id: 'L02', t0: 150, t1: 153, text: 'hook hook', conf: 0.63 }),
  makeLyricPhrase({ key: '193.0-199.0', id: 'L03', t0: 193, t1: 199, text: 'go to bed', conf: 0.28, doubtful: true, counts: false })] })

describe('LyricsPanel', () => {
  it('shows nothing without a music track', async () => {
    mockGet('/api/lyrics', makeLyrics({ has_track: false }))
    const { container } = setup(<LyricsPanel folder="/data" />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('offers to find the lyrics and starts the run', async () => {
    mockGet('/api/lyrics', makeLyrics()); const seen = recordRequests('/api/lyrics'); mockPost('/api/lyrics', { started: true })
    const { user } = setup(<LyricsPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Find the lyrics' }))
    await waitFor(() => expect(seen.some(r => r.method === 'POST')).toBe(true))
    expect(seen.find(r => r.method === 'POST')?.body).toEqual({ folder: '/data' })
  })

  it('shows progress while listening and blocks a second start', async () => {
    mockGet('/api/lyrics', makeLyrics({ building: true, log: 'listening to the track' }))
    setup(<LyricsPanel folder="/data" />)
    expect(await screen.findByText('listening to the track')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Listening…' })).toBeDisabled()
  })

  it('lists the phrases with the share sung and marks the doubtful one as not counted', async () => {
    mockGet('/api/lyrics', found())
    setup(<LyricsPanel folder="/data" />)
    expect(await screen.findByText('3 phrases, 12.6 s sung (5%), en')).toBeInTheDocument()
    expect(screen.getByLabelText('Words at 1:40')).toHaveValue('line one'); expect(screen.getByText('doubtful, not counted')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Count it' })).toBeInTheDocument()
  })

  it('corrects a phrase: not sung, count it, and new words', async () => {
    mockGet('/api/lyrics', found()); const seen = recordRequests('/api/lyrics/phrase'); mockPost('/api/lyrics/phrase', makeLyricPhrase())
    const { user } = setup(<LyricsPanel folder="/data" />)
    await user.click((await screen.findAllByRole('button', { name: 'Not sung' }))[1])
    await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', key: '150.0-153.0', deleted: true })
    await user.click(screen.getByRole('button', { name: 'Count it' }))
    await waitFor(() => expect(seen).toHaveLength(2)); expect(seen[1].body).toEqual({ folder: '/data', key: '193.0-199.0', keep: true })
    const box = screen.getByLabelText('Words at 1:40'); await user.clear(box); await user.type(box, 'the true words'); await user.tab()
    await waitFor(() => expect(seen).toHaveLength(3)); expect(seen[2].body).toEqual({ folder: '/data', key: '100.0-103.0', text: 'the true words' })
  })

  it('says when the track is instrumental, when it is out of date, and resets', async () => {
    mockGet('/api/lyrics', makeLyrics({ exists: true, instrumental: true, stale: true, phrases: 1, sung_s: 1, duration_s: 100 })); const del = recordRequests('/api/lyrics'); mockDelete('/api/lyrics', { reset: true })
    const { user } = setup(<LyricsPanel folder="/data" />)
    expect(await screen.findByText('instrumental: no singing found')).toBeInTheDocument(); expect(screen.getByText(/out of date: the track has changed/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reset' })); await waitFor(() => expect(del.some(r => r.method === 'DELETE')).toBe(true))
  })

  it('shows why a run failed', async () => {
    mockGet('/api/lyrics', makeLyrics({ error: 'ModuleNotFoundError: No module named faster_whisper' }))
    setup(<LyricsPanel folder="/data" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Finding the lyrics failed: ModuleNotFoundError')
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/lyrics', found())
    const { container } = setup(<LyricsPanel folder="/data" />)
    await screen.findByLabelText('Words at 1:40')
    expect(await axe(container)).toHaveNoViolations()
  })
})
