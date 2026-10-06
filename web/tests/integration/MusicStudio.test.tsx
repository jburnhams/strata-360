import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import MusicStudio from '../../src/components/MusicStudio'
import { screen, setup, waitFor, within } from '../utils/render'
import { makeStudioState, makeStudioPreview, makeMusicScore, makeStudioGrid } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests } from '../utils/api'
import { axe } from 'vitest-axe'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('MusicStudio', () => {
  it('asks for the track to be analysed when it has not been', async () => {
    mockGet('/api/music/studio', makeStudioState({ grid: null }))
    setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/has not been analysed/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse the track' })).toBeInTheDocument(); expect(screen.queryByText('What to build')).not.toBeInTheDocument()
  })

  it('sends the analyse request and shows what came back', async () => {
    mockGet('/api/music/studio', makeStudioState({ grid: null })); const seen = recordRequests('/api/music/studio/analyse')
    const { user } = setup(<MusicStudio folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Analyse the track' })); await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data' })
  })

  it('shows a failed analysis', async () => {
    mockGet('/api/music/studio', makeStudioState({ grid: null })); mockError('/api/music/studio/analyse', 400, 'could not read the audio', 'post')
    const { user } = setup(<MusicStudio folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Analyse the track' })); expect(await screen.findByRole('alert')).toHaveTextContent('could not read the audio')
  })

  it('shows the key, tempo and bars of the track and its loudness bar by bar', async () => {
    setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/120 bpm · A minor · 8 bars of 2.00 s · 0:16 long/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Loudness of each of the track's 8 bars/ })).toBeInTheDocument()
  })

  it('warns when the key is a guess', async () => {
    mockGet('/api/music/studio', makeStudioState({ grid: makeStudioGrid({ key: { tonic: 0, mode: 'major', name: 'C major', confidence: 0.1 } }) }))
    setup(<MusicStudio folder="/data" />); expect(await screen.findByText(/key is a guess/)).toBeInTheDocument()
  })

  it('says when the track plays as it is', async () => {
    mockPost('/api/music/studio/preview', makeStudioPreview({ plan: { bars: [0, 1, 2, 3, 4, 5, 6, 7], runs: [[0, 8]], joins: [], worst_join: 0 } })); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/the track played as it is/)).toBeInTheDocument()
  })

  it('previews with the track length and the arc preset at first, then draws the plan', async () => {
    const seen = recordRequests('/api/music/studio/preview'); setup(<MusicStudio folder="/data" />)
    await screen.findByLabelText('Preview of the build'); expect(seen.at(-1)?.body).toMatchObject({ folder: '/data', length_s: 16, preset: 'arc', windows: [] })
    expect(screen.getByText(/8 bars · 0:16 · 3 stretches of the track joined by 2 cuts, worst join 30%/)).toBeInTheDocument()
    expect(screen.getAllByTestId('run')).toHaveLength(3); expect(screen.getAllByTestId('join')).toHaveLength(2); expect(screen.getAllByTestId('stretch')).toHaveLength(3)
    expect(screen.getAllByTestId('uses').length).toBe(8)
  })

  it('previews again with a new length and preset', async () => {
    const seen = recordRequests('/api/music/studio/preview'); const { user } = setup(<MusicStudio folder="/data" />)
    await screen.findByLabelText('Preview of the build'); const len = screen.getByLabelText('Length (seconds)'); await user.clear(len); await user.type(len, '60'); await user.selectOptions(screen.getByLabelText(/Intensity over the film/), 'build')
    await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ length_s: 60, preset: 'build' })); expect(screen.getByText('rising to the finish')).toBeInTheDocument()
  })

  it('shows the layers and the intensity of each phrase', async () => {
    setup(<MusicStudio folder="/data" />); await screen.findByLabelText('Preview of the build')
    expect(screen.getAllByRole('button', { name: /^Phrase \d/ })).toHaveLength(2); expect(screen.getByRole('button', { name: /Phrase 1 .*full/ })).toBeInTheDocument(); expect(screen.getByRole('button', { name: /Phrase 2 .*steady/ })).toBeInTheDocument()
    for (const n of ['drums', 'bass', 'other', 'vocals']) expect(within(screen.getByRole('img', { name: `${n} layer by bar` })).getAllByText((_, el) => el?.getAttribute('data-stem') === n)).toHaveLength(8)
  })

  it('a click on a phrase raises its level, switches to manual and previews those levels', async () => {
    const seen = recordRequests('/api/music/studio/preview'); const { user } = setup(<MusicStudio folder="/data" />)
    await user.click(await screen.findByRole('button', { name: /Phrase 2 .*steady/ }))
    await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ preset: 'manual', levels: [0.9, 0.9, 0.9, 0.9, 0.65, 0.65, 0.65, 0.65] })); expect(screen.getByText('set by hand below')).toBeInTheDocument()
  })

  it('adds and removes a moment for the original singing and sends it', async () => {
    const seen = recordRequests('/api/music/studio/preview'); const { user } = setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/instrumental throughout/)).toBeInTheDocument(); await user.click(screen.getByRole('button', { name: 'add a moment' }))
    await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ windows: [[8, 16]] })); await user.click(screen.getByRole('button', { name: 'remove' })); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ windows: [] }))
  })

  it('says in which bars the singing plays', async () => {
    mockPost('/api/music/studio/preview', makeStudioPreview({ windows: [[2, 4]], gains: { ...makeStudioPreview().gains, vocals: [0, 0, 1, 1, 0, 0, 0, 0] } }))
    setup(<MusicStudio folder="/data" />); expect(await screen.findByText(/singing plays in bars 3 to 4/)).toBeInTheDocument()
  })

  it('shows a refused preview', async () => {
    mockError('/api/music/studio/preview', 409, 'analyse the track first', 'post'); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText('analyse the track first')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Build this music' })).toBeDisabled()
  })

  it('starts a build with the settings on screen', async () => {
    const seen = recordRequests('/api/music/studio/build'); const { user } = setup(<MusicStudio folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Build this music' })); await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', length_s: 16, preset: 'arc', windows: [] })
  })

  it('shows a build that refused to start', async () => {
    mockPost('/api/music/studio/build', { started: false, reason: 'a track is already being built' }); const { user } = setup(<MusicStudio folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Build this music' })); expect(await screen.findByRole('alert')).toHaveTextContent('already being built')
  })

  it('shows a build in progress with its last log line, and a failed one with its error', async () => {
    mockGet('/api/music/studio', makeStudioState({ building: true, log: 'separating the stems' })); const { unmount } = setup(<MusicStudio folder="/data" />)
    expect(await screen.findByRole('button', { name: 'Building…' })).toBeDisabled(); expect(screen.getByText('separating the stems')).toBeInTheDocument(); unmount()
    mockGet('/api/music/studio', makeStudioState({ error: 'No module named demucs' })); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/The build failed: No module named demucs/)).toBeInTheDocument()
  })

  it('plays the built music and describes it', async () => {
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore({ windows: [[4, 6]], stray_vocal_db: -23 }) })); setup(<MusicStudio folder="/data" />)
    const box = await screen.findByLabelText('The built music'); expect(within(box).getByLabelText('Built music')).toHaveAttribute('src', expect.stringContaining('/api/music/built/audio?'))
    expect(within(box).getByText(/0:40 · 120 bpm · A minor · 9 bars in 3 stretches · worst join 5%/)).toBeInTheDocument(); expect(within(box).getByText(/singing plays in 1 moment.*23 dB below/)).toBeInTheDocument()
  })

  it('says a built instrumental has no singing', async () => {
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore() })); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/Instrumental throughout. No singing outside them/)).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore() })); const { container } = setup(<MusicStudio folder="/data" />); await screen.findByLabelText('Preview of the build')
    expect(await axe(container)).toHaveNoViolations()
  })
})
