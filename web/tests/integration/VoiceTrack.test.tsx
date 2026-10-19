import { afterEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import VoiceTrack, { blocksOf, refitText } from '../../src/components/VoiceTrack'
import Timeline from '../../src/components/Timeline'
import type { EditState } from '../../src/api'
import { setup, screen, waitFor, within } from '../utils/render'
import { makeEditResponse, makeEditState, makePlanSegment, makeVoiceTimeline, makeVoiceTimelineLine } from '../utils/factories'
import { mockError, mockGet, mockPost, recordRequests } from '../utils/api'
import { stubMedia } from '../utils/media'

type Plan = NonNullable<EditState['plan']>
const plan = (o: Partial<Plan> = {}): Plan => ({
  source: 'script', generated_at: 'utc', film: { length_s: 20, beats: 40, bpm: 120 }, clips_in_plan: 3, missing_clips: [], orphaned_overrides: [], technique_seconds: {}, warnings: [],
  segments: [
    makePlanSegment({ id: 'w0', clip: 'CAM_1', film_start_s: 0, dur_s: 4, item: 0, role: 'clip' }),
    makePlanSegment({ id: 'w1', clip: 'CAM_2', film_start_s: 4, dur_s: 2, item: 1, role: 'vo' }),
    makePlanSegment({ id: 'w2', clip: 'CAM_2', film_start_s: 6, dur_s: 2.5, item: 1, role: 'vo' }),
    makePlanSegment({ id: 'w3', clip: 'CAM_3', film_start_s: 8.5, dur_s: 11.5, item: 2, role: 'broll' }),
  ],
  beat_sync: { seek_s: 0, delay_s: 0, off_beat: [{ cut: 3, film_s: 8.5, off_ms: 24, why: 'the words in clip 0021 end there' }] },
  ...o,
})
const timeline = () => makeVoiceTimeline({
  lines: [makeVoiceTimelineLine({ seg: 'nA', text: 'Into the first climb', item: 1, start_s: 4.12, speak_s: 3.8 }), makeVoiceTimelineLine({ seg: 'nB', text: 'The long descent', item: 2, start_s: 8.62, speak_s: 2, source: 'recorded', has_recording: true, fit: 'over', overrun_s: 0.4 })],
  beats: [0, 0.5, 1, 1.5, 2], bars: [0, 2], synced: true, length_s: 20,
})

function stubRecorder() {
  const trackStop = vi.fn(); let onstop: (() => void) | null = null; let ondata: ((e: { data: Blob }) => void) | null = null
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: trackStop }] }) }, configurable: true })
  class MockMediaRecorder {
    mimeType = 'audio/webm'
    start = vi.fn()
    stop = () => { ondata?.({ data: new Blob(['take']) }); onstop?.() }
    set ondataavailable(cb: (e: { data: Blob }) => void) { ondata = cb }
    set onstop(cb: () => void) { onstop = cb }
  }
  vi.stubGlobal('MediaRecorder', MockMediaRecorder)
  return trackStop
}

describe('VoiceTrack', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('draws the narration lines above the windows with their measured lengths', async () => {
    mockGet('/api/voiceover/timeline', timeline())
    setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div>the strip</div></VoiceTrack>)
    const lines = await screen.findByRole('group', { name: 'Narration lines' })
    const items = within(lines).getAllByRole('button')
    expect(items.map(i => i.getAttribute('aria-label'))).toEqual(['Line 1: Into the first climb', 'Line 2: The long descent'])
    expect(items[0]).toHaveStyle({ left: '20.6%', width: '19%' })
    expect(items[1]).toHaveAttribute('title', expect.stringContaining('your recording · too long by 0.4 s'))
    expect(screen.getByText('the strip')).toBeInTheDocument()
  })

  it('draws the script blocks as bands over the windows', async () => {
    mockGet('/api/voiceover/timeline', timeline())
    setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    const blocks = within(await screen.findByRole('list', { name: 'Script blocks' })).getAllByRole('listitem')
    expect(blocks.map(b => b.getAttribute('aria-label'))).toEqual(['Item 1: you, 4.0 s', 'Item 2: narration, 4.5 s', 'Item 3: b-roll, 11.5 s'])
    expect(blocks[1]).toHaveStyle({ left: '20%', width: '22.5%' })
  })

  it('draws the beat ticks and marks the cuts off the beat with their reason', async () => {
    mockGet('/api/voiceover/timeline', timeline())
    setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    const ticks = await screen.findByRole('img', { name: '5 beats and 2 bar lines of the music' })
    expect(ticks.querySelectorAll('line')).toHaveLength(5)
    expect([...ticks.querySelectorAll('line')].map(l => l.getAttribute('y2'))).toEqual(['10', '5', '5', '5', '10'])
    expect(screen.getByRole('img', { name: 'Cut 3 is 24 ms off the beat: the words in clip 0021 end there' })).toHaveStyle({ left: '42.5%' })
  })

  it("says the ticks are the plan's own tempo when the cuts were not synced to the music", async () => {
    mockGet('/api/voiceover/timeline', makeVoiceTimeline({ beats: [0, 0.5], bars: [0], length_s: 20 }))
    setup(<VoiceTrack folder="/data" plan={plan({ beat_sync: null })} onChanged={vi.fn()}><div /></VoiceTrack>)
    expect(await screen.findByRole('img', { name: "2 beats and 1 bar lines of the plan's tempo" })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Narration lines' })).not.toBeInTheDocument()
  })

  it('has no blocks for a plan made by the beat planner', async () => {
    mockGet('/api/voiceover/timeline', makeVoiceTimeline())
    setup(<VoiceTrack folder="/data" plan={plan({ source: 'beats', segments: [makePlanSegment({ id: 'w0' })] })} onChanged={vi.fn()}><div>strip</div></VoiceTrack>)
    expect(await screen.findByText('strip')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Script blocks' })).not.toBeInTheDocument())
  })

  it('shows the windows and the error when the voice timeline cannot be loaded', async () => {
    mockError('/api/voiceover/timeline', 500, 'no timeline')
    setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div>strip</div></VoiceTrack>)
    expect(await screen.findByText('no timeline')).toBeInTheDocument()
    expect(screen.getByText('strip')).toBeInTheDocument()
  })

  it('opens a line to hear its take and record it', async () => {
    mockGet('/api/voiceover/timeline', timeline())
    const { user } = setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    await user.click(await screen.findByRole('button', { name: 'Line 2: The long descent' }))
    expect(screen.getByText(/2\.0 s of speech in 4\.5 s of picture · your recording/)).toBeInTheDocument()
    expect(screen.getByLabelText("This line's take")).toHaveAttribute('src', expect.stringContaining('seg=nB&source=recorded'))
    expect(screen.getByRole('button', { name: '● record again' })).toBeInTheDocument()
  })

  it('does not offer to play a line that has not been spoken yet', async () => {
    mockGet('/api/voiceover/timeline', makeVoiceTimeline({ lines: [makeVoiceTimelineLine({ text: 'Not yet', estimated: true })] }))
    const { user } = setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    await user.click(await screen.findByRole('button', { name: 'Line 1: Not yet' }))
    expect(screen.getByText(/estimated from the words: not spoken yet/)).toBeInTheDocument()
    expect(screen.queryByLabelText("This line's take")).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '● record' })).toBeInTheDocument()
  })

  it('records a line again, re-fits its block, speaks the track and reloads the film', async () => {
    const trackStop = stubRecorder(); const onChanged = vi.fn()
    mockGet('/api/voiceover/timeline', timeline())
    mockPost('/api/voiceover/record', { ok: true, refit: { mode: 'refit', seg: 'nA', item: 1, delta_s: 1, beats: 2, changed: ['w2'], warnings: ['item 2: the new take needs 5.5 s of picture'] } })
    const recs = recordRequests('/api/voiceover/record'), builds = recordRequests('/api/voiceover/build'), loads = recordRequests('/api/voiceover/timeline')
    const { user } = setup(<VoiceTrack folder="/data" plan={plan()} onChanged={onChanged}><div /></VoiceTrack>)
    await user.click(await screen.findByRole('button', { name: 'Line 1: Into the first climb' }))
    await user.click(screen.getByRole('button', { name: '● record' }))
    await user.click(await screen.findByRole('button', { name: '■ stop' }))
    expect(await screen.findByText('Item 2 grew by 1.0 s (2 beats); every other shot is unchanged.')).toBeInTheDocument()
    expect(screen.getByText('item 2: the new take needs 5.5 s of picture')).toBeInTheDocument()
    expect(recs[0].url.searchParams.get('seg')).toBe('nA')
    await waitFor(() => expect(builds).toHaveLength(1)); await waitFor(() => expect(onChanged).toHaveBeenCalled()); await waitFor(() => expect(loads.length).toBeGreaterThan(0))
    expect(trackStop).toHaveBeenCalled()
  })

  it('shows why a recording failed', async () => {
    stubRecorder(); mockGet('/api/voiceover/timeline', timeline()); mockError('/api/voiceover/record', 400, 'could not read that audio', 'post')
    const { user } = setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    await user.click(await screen.findByRole('button', { name: 'Line 1: Into the first climb' }))
    await user.click(screen.getByRole('button', { name: '● record' })); await user.click(await screen.findByRole('button', { name: '■ stop' }))
    expect(await screen.findByText('could not read that audio')).toBeInTheDocument()
  })

  it('says when the microphone cannot be used', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: vi.fn().mockRejectedValue(new Error('denied')) }, configurable: true })
    mockGet('/api/voiceover/timeline', timeline())
    const { user } = setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    await user.click(await screen.findByRole('button', { name: 'Line 1: Into the first climb' }))
    await user.click(screen.getByRole('button', { name: '● record' }))
    expect(await screen.findByText(/could not use a microphone/)).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/voiceover/timeline', timeline())
    const { container } = setup(<VoiceTrack folder="/data" plan={plan()} onChanged={vi.fn()}><div /></VoiceTrack>)
    await screen.findByRole('group', { name: 'Narration lines' })
    expect(await axe(container)).toHaveNoViolations()
  })

  it('is drawn over the windows on the timeline', async () => {
    stubMedia()
    mockGet('/api/edit', makeEditResponse({ edit: makeEditState({ plan: plan() }) }))
    mockGet('/api/voiceover/timeline', timeline())
    setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
    expect(await screen.findByRole('group', { name: 'Narration lines' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'The film, segment by segment' })).toBeInTheDocument()
  })
})

describe('refitText', () => {
  it.each([
    [{ mode: 'refit', item: 0, delta_s: -0.5, beats: -1 }, 'Item 1 shrank by 0.5 s (1 beat); every other shot is unchanged.'],
    [{ mode: 'same', item: 2 }, "The new take fits item 3's picture as it is: nothing moved."],
    [{ mode: 'replan' }, 'The line is spoken over a generated clip, so the film was planned again.'],
    [{ mode: 'none', reason: 'no voice to measure the line with' }, 'The take is saved, but the film was not re-fitted: no voice to measure the line with.'],
    [{ mode: 'error' }, 'The take is saved, but the film was not re-fitted: unknown reason.'],
    [null, 'The take is saved.'],
  ] as const)('describes %o', (r, text) => { expect(refitText(r as never)).toBe(text) })
})

describe('blocksOf', () => {
  it('joins consecutive windows of one item and skips windows with no item', () => {
    expect(blocksOf(plan({ segments: [...plan().segments, makePlanSegment({ id: 'x', film_start_s: 20, dur_s: 1 })] })).map(b => [b.item, b.windows, b.dur])).toEqual([[0, 1, 4], [1, 2, 4.5], [2, 1, 11.5]])
  })
})
