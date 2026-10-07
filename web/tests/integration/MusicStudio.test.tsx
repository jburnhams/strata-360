import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import MusicStudio from '../../src/components/MusicStudio'
import { screen, setup, waitFor, within } from '../utils/render'
import { makeStudioState, makeStudioPreview, makeMusicScore, makeStudioGrid, makeScorePlan } from '../utils/factories'
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

  it('follows the footage by default when the film has signals, at the length of the film, and shows what drove the curve', async () => {
    mockGet('/api/music/studio', makeStudioState({ footage: { length_s: 120, used: ['motion', 'crowd'] } }))
    mockPost('/api/music/studio/preview', makeStudioPreview({ why: { signals: [{ name: 'crowd', weight: 2, values: [0, 0.5, 1, 1, 0, 0, 0, 0] }, { name: 'technique', weight: 1, values: [0.2, 0.2, 0.2, 0.2, 0.9, 0.9, 0.9, 0.9] }], speech: [false, false, true, true, false, false, false, false] } }))
    const seen = recordRequests('/api/music/studio/preview'); setup(<MusicStudio folder="/data" />)
    const why = await screen.findByLabelText('What drove the intensity'); expect(seen.at(-1)?.body).toMatchObject({ length_s: 120, preset: 'footage' })
    expect(screen.getByLabelText(/Intensity over the film/)).toHaveValue('footage'); expect(screen.getByRole('option', { name: 'follow the footage' })).toBeInTheDocument()
    expect(within(screen.getByRole('img', { name: 'crowd sound by bar' })).getAllByText((_, el) => el?.getAttribute('data-signal') === 'crowd')).toHaveLength(8); expect(within(why).getByText('shot energy')).toBeInTheDocument()
    expect(within(screen.getByRole('img', { name: 'speech by bar' })).getAllByText((_, el) => el?.className.includes('bg-sky-500') ?? false)).toHaveLength(2)
  })

  it('does not offer the footage when the film has no signals, nor show a reason for a preset curve', async () => {
    setup(<MusicStudio folder="/data" />); await screen.findByLabelText('Preview of the build')
    expect(screen.queryByRole('option', { name: 'follow the footage' })).not.toBeInTheDocument(); expect(screen.queryByLabelText('What drove the intensity')).not.toBeInTheDocument()
  })

  it('writes minutes and seconds without a 60', async () => {
    mockPost('/api/music/studio/preview', makeStudioPreview({ length_s: 179.9 })); setup(<MusicStudio folder="/data" />)
    expect((await screen.findAllByText(/3:00/)).length).toBeGreaterThan(0); expect(screen.queryByText(/2:60/)).not.toBeInTheDocument()
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
    await user.click(await screen.findByRole('button', { name: 'Build this music' })); await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', length_s: 16, preset: 'arc', windows: [], fidelity: 0.75, pins: {}, style: '', takes: {} })
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

describe('MusicStudio: true to the track, new bars and the checks', () => {
  it('previews at the fidelity on the slider and its named stops', async () => {
    const seen = recordRequests('/api/music/studio/preview'); const { user } = setup(<MusicStudio folder="/data" />)
    await screen.findByLabelText('Preview of the build'); expect(seen.at(-1)?.body).toMatchObject({ fidelity: 0.75, pins: {} }); expect(screen.getByText('Extended', { selector: 'span' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remix' })); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ fidelity: 0.5 }))
    expect(screen.getByText(/about half the bars new/)).toBeInTheDocument()
  })

  it('names a setting between two stops', async () => {
    const { FIDELITY_STOPS, fidelityName } = await import('../../src/components/MusicStudio')
    expect(FIDELITY_STOPS).toHaveLength(5); expect(fidelityName(1)).toBe('The record'); expect(fidelityName(0.6)).toBe('between Extended and Remix'); expect(fidelityName(0)).toBe('In its style')
  })

  it('asks for the style and warns when there is no generator', async () => {
    const { user } = setup(<MusicStudio folder="/data" />); await screen.findByLabelText('Preview of the build')
    expect(screen.getByText(/ACE-Step is not installed/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'The record' })); expect(screen.queryByText(/ACE-Step is not installed/)).not.toBeInTheDocument(); expect(screen.queryByLabelText(/The track's style/)).not.toBeInTheDocument()
  })

  it('asks for a style when ACE-Step is there and sends it with the build', async () => {
    mockGet('/api/music/studio', makeStudioState({ generator: true })); const seen = recordRequests('/api/music/studio/build'); const { user } = setup(<MusicStudio folder="/data" />)
    await screen.findByLabelText('Preview of the build'); expect(screen.getByText(/Name the style/)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/The track's style/), 'rap rock'); expect(screen.queryByText(/Name the style/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Build this music' })); await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ style: 'rap rock', fidelity: 0.75 })
  })

  it('starts from the last build\'s style and fidelity', async () => {
    mockGet('/api/music/studio', makeStudioState({ generator: true, built: makeMusicScore({ style: 'funk', fidelity: 0.5 }) })); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByDisplayValue('funk')).toBeInTheDocument(); expect(screen.getByLabelText('Fidelity')).toHaveValue('0.5')
  })

  it('draws the score and pins a section to the track, then to new bars, then lets it go', async () => {
    mockPost('/api/music/studio/preview', makeStudioPreview({ score: makeScorePlan({ unreachable: [5], sung: [{ first: 2, end: 4, form: 'a' }] }) })); const seen = recordRequests('/api/music/studio/preview')
    const { user } = setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/Score: 50% the track's own bars, 1 section of new bars \(1 to make\)/)).toBeInTheDocument(); expect(screen.getAllByTestId('sung')).toHaveLength(1)
    expect(screen.getByText(/never gets this quiet or loud: bar 6/)).toBeInTheDocument(); expect(screen.getByText(/Without ACE-Step these play/)).toBeInTheDocument()
    const sec = () => screen.getByRole('button', { name: /^Bars 5 to 8/ }); expect(sec()).toHaveAccessibleName(/new bars, not made yet/)
    await user.click(sec()); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ pins: { 4: 'original' } }))
    await user.click(sec()); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ pins: { 4: 'generate' } }))
    await user.click(sec()); await waitFor(() => expect(seen.at(-1)?.body).toMatchObject({ pins: {} }))
  })

  it('says when every new section is made already', async () => {
    mockPost('/api/music/studio/preview', makeStudioPreview({ score: makeScorePlan({ sections: makeScorePlan().sections.map(s => ({ ...s, new: false })) }) })); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/\(all made already\)/)).toBeInTheDocument()
  })

  it('shows the checks of the built track', async () => {
    const check = { ok: false, grid: { ok: false, worst_ms: 55, median_ms: 6, off_bars: [3] }, length: { ok: true, length_s: 40, trimmed_s: 1.2, padded_s: 0, faded: true }, stray_vocal_db: -40, singing_in_generated: [4], failed: [12] }
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore({ check, fidelity: 0.75 }) })); setup(<MusicStudio folder="/data" />)
    const ck = within(await screen.findByRole('list', { name: 'Checks' }))
    expect(ck.getByText(/worst 55 ms, typical 6 ms; bars 4 are more than 40 ms off/)).toHaveClass('text-red-700'); expect(ck.getByText(/1.2 s cut with a fade/)).toHaveClass('text-emerald-700')
    expect(ck.getByText(/Singing outside the sung moments at -40 dB/)).toBeInTheDocument(); expect(ck.getByText(/Singing heard in the new bars from bar 5/)).toBeInTheDocument(); expect(ck.getByText(/not made from bar 13/)).toBeInTheDocument()
    expect(screen.getByText(/· Extended$/)).toBeInTheDocument()
  })

  it('says when the beat check did not run and when nothing sang', async () => {
    const check = { ok: true, grid: { ok: null, why: 'the track is too short' }, length: { ok: true, length_s: 40, trimmed_s: 0, padded_s: 2, faded: false }, stray_vocal_db: null, singing_in_generated: [], failed: [] }
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore({ check }) })); setup(<MusicStudio folder="/data" />)
    const ck = within(await screen.findByRole('list', { name: 'Checks' })); expect(ck.getByText(/Beat check not run: the track is too short/)).toBeInTheDocument(); expect(ck.getByText(/2 s of silence at the end/)).toBeInTheDocument(); expect(ck.getByText(/No singing outside/)).toBeInTheDocument()
  })

  it('lists the takes of new bars, picks one and asks for another, and the build uses them', async () => {
    const generated = [{ first: 4, end: 12, key: 'k1', mode: 'repaint' as const, ok: true, seed: 1, gain: 0.45, singing_db: -50, all_takes: [{ seed: 0, action: 'regenerate' as const, ratio: 1.2, worst_ms: null, why: 'tempo' }, { seed: 1, action: 'as is' as const, ratio: 1, worst_ms: 8 }, { seed: 2, action: 'stretched' as const, ratio: 0.99, worst_ms: 12 }] },
      { first: 20, end: 24, ok: false, kept_original: true, why: 'no style given' }]
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore({ generated }) })); const seen = recordRequests('/api/music/studio/build'); const { user } = setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText(/repainted inside the track · take 1 · level ×0.45 · vocals -50 dB/)).toBeInTheDocument(); expect(screen.getByText(/the track's own bars: no style given/)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'take 0: wrong tempo' })).toBeDisabled(); expect(screen.getByRole('radio', { name: 'take 1: in time' })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: 'take 2: stretched to time' })); expect(screen.getByText(/Build again to use the takes chosen/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Build this music' })); await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ takes: { k1: 2 } })
    await user.click(screen.getByRole('button', { name: 'another take' })); expect(screen.getByRole('button', { name: 'take 3 at the next build' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'back to the first good take' })); expect(screen.getByRole('radio', { name: 'take 1: in time' })).toBeChecked(); expect(screen.queryByText(/Build again/)).not.toBeInTheDocument()
  })

  it('says when no take kept time', async () => {
    const generated = [{ first: 4, end: 12, key: 'k1', mode: 'cover' as const, ok: false, seed: null, kept_original: true, why: 'no take kept time with the grid', takes: [{ seed: 0, action: 'repaint' as const, ratio: 1, worst_ms: 60 }] }]
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore({ generated }) })); setup(<MusicStudio folder="/data" />)
    expect(await screen.findByText('no take kept time yet')).toBeInTheDocument(); expect(screen.getByRole('radio', { name: 'take 0: off the beat' })).toBeDisabled()
  })

  it('has no accessibility violations with the score and takes', async () => {
    mockPost('/api/music/studio/preview', makeStudioPreview({ score: makeScorePlan() }))
    mockGet('/api/music/studio', makeStudioState({ built: makeMusicScore({ generated: [{ first: 4, end: 12, key: 'k1', mode: 'text', ok: true, seed: 0, takes: [{ seed: 0, action: 'as is', ratio: 1, worst_ms: 5 }] }] }) }))
    const { container } = setup(<MusicStudio folder="/data" />); await screen.findByText(/Score:/); await screen.findByText(/made from the style alone/)
    expect(await axe(container)).toHaveNoViolations()
  })
})
