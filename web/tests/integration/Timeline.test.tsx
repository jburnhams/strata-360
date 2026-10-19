import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { setup } from '../utils/render'
import Timeline from '../../src/components/Timeline'
import { makeClipInfo, makeEditResponse, makeEditState, makePlanSegment } from '../utils/factories'
import { mockGet, mockPost, mockError, mockPending, recordRequests } from '../utils/api'
import { stubBrowserApis, stubMedia, stubRect } from '../utils/media'
import { fireEvent } from '@testing-library/react'


describe('Timeline', () => {
  afterEach(() => { vi.clearAllMocks() })
  beforeEach(() => {
    stubMedia()
  })

  it('shows a loading skeleton initially', async () => {
    mockPending('/api/edit')
    const { getByLabelText } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
    expect(getByLabelText('Loading Timeline')).toBeInTheDocument()
  })

  it('shows an error message if loading fails', async () => {
    mockError('/api/edit', 500, 'Server error')
    const { findByText } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
    expect(await findByText('Server error')).toBeInTheDocument()
  })

  it('renders a plan when data is loaded', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 30, beats: 60, bpm: 120 }, segments: [makePlanSegment({ id: 'w1', clip: 'CAM_1', technique: 'pan', dur_s: 5, film_start_s: 0, clip_start_s: 10, options: [{ tech: 'pan', score: 1 }, { tech: 'static', score: 0.5 }] })], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { pan: 5 }, warnings: [] }
      },
      script: { w1: { text: 'Hello', says: [], words: 1, budget: 1 } }
    })
    mockGet('/api/edit', editResp)

    const clips = [makeClipInfo({ id: 'CAM_1', thumb: 'best' })]
    const { findByText, getByRole, getByDisplayValue, getByText, getAllByText } = setup(<Timeline folder="/data" clips={clips} onOpenClip={vi.fn()} />)

    expect(await findByText('Plan')).toBeInTheDocument()
    expect(getByDisplayValue('90')).toBeInTheDocument() // Film length
    expect(getByDisplayValue('120')).toBeInTheDocument() // Tempo

    // Check segment rendering
    expect(getByText('0:00.0', { exact: false })).toBeInTheDocument()
    expect(getAllByText('5s', { exact: false })[0]).toBeInTheDocument()
    expect(getByText('1')).toBeInTheDocument() // clip name (shortened from CAM_1)
    expect(getByText('▶ 0:10.0–0:15.0')).toBeInTheDocument()

    // Technique select
    const techSelect = getByDisplayValue('pan')
    expect(techSelect).toBeInTheDocument()
    expect(techSelect).toHaveRole('combobox')

    // Script text
    expect(getByText('Hello')).toBeInTheDocument()
  })

  it('handles proposing a film', async () => {
    const editResp = makeEditResponse({ edit: { settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' }, overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} }, plan: null } })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/propose', { edit: editResp.edit })

    const seenPropose = recordRequests('/api/edit/propose')

    const { findByRole, findByText, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
    const proposeBtn = await findByRole('button', { name: 'Propose a film' })
    await user.click(proposeBtn)

    expect(seenPropose).toHaveLength(1)
    expect(seenPropose[0].body).toEqual({ folder: '/data', length_s: 90, bpm: 120, keep: true, replace: true })
  })

  it('asks before the beat planner replaces a film planned from the script', async () => {
    const plan = { source: 'script', generated_at: '2026-10-02T10:00:00Z', film: { length_s: 60, beats: 120, bpm: 120 }, segments: [], clips_in_plan: 0, missing_clips: [], orphaned_overrides: [], technique_seconds: {}, warnings: [] }
    const editResp = makeEditResponse({ edit: makeEditState({ plan: plan as never }) }); mockGet('/api/edit', editResp); mockPost('/api/edit/propose', { edit: editResp.edit })
    const seen = recordRequests('/api/edit/propose'); const { findByRole, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false); await user.click(await findByRole('button', { name: 'Re-plan' }))
    expect(ask).toHaveBeenCalledWith(expect.stringContaining('planned from your script')); expect(seen).toHaveLength(0)
    ask.mockReturnValue(true); await user.click(await findByRole('button', { name: 'Re-plan' })); expect(seen).toHaveLength(1); ask.mockRestore()
  })

  it('shows a speed ramp and turns ramps off with a re-plan', async () => {
    const ramp = { dur_s: 5, lead_s: 1.75, ramp_s: 0.6, tail_s: 0.3, speed: 12.4, src_dur_s: 52, lands: true }
    const seg = makePlanSegment({ id: 'w1', clip: 'CAM_1', technique: 'follow_runner', clip_start_s: 10, dur_s: 5, ramp, src_dur_s: 52, ramp_from: 'hold_wide' })
    const report = [{ id: 'w1', clip: 'CAM_1', film_start_s: 0, dur_s: 5, from_s: 15, to_s: 62, speed: 12.4, lands: true, technique_was: 'hold_wide' }]
    const editResp = makeEditResponse({ edit: makeEditState({ plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [seg], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { follow_runner: 5 }, warnings: [], hyperlapse: report } }) })
    mockGet('/api/edit', editResp); mockPost('/api/edit/propose', { edit: editResp.edit })
    const seen = recordRequests('/api/edit/propose')
    const { findByText, getByText, getByRole, user } = setup(<Timeline folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} onOpenClip={vi.fn()} />)
    const badge = await findByText('⏩ ×12 to 1:02.0')
    expect(badge).toHaveAttribute('title', 'a speed ramp: 1.8 s at real speed, then up to 12x through 47 s of quiet running, landing where the next window starts (was hold wide: a ramp follows your heading)')
    expect(getByText('· 1 speed ramp through 0.8 min of running', { exact: false })).toBeInTheDocument()
    const box = getByRole('checkbox', { name: 'Speed ramps' }); expect(box).toBeChecked()
    await user.click(box)
    expect(seen).toHaveLength(1); expect(seen[0].body).toEqual({ folder: '/data', hyperlapse: false, keep: true, replace: true })
  })

  it('asks for another version of the plan', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 30, beats: 60, bpm: 120 }, segments: [makePlanSegment()], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/propose', { edit: editResp.edit })
    const seenPropose = recordRequests('/api/edit/propose')
    const { findByRole, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
    await user.click(await findByRole('button', { name: 'Another version' }))
    expect(seenPropose).toHaveLength(1)
    expect(seenPropose[0].body).toEqual({ folder: '/data', seed: 2, keep: false, replace: true })
  })

  it('handles overrides (locking a segment)', async () => {
    const planSeg = makePlanSegment({ id: 'w1', locked: false })
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [planSeg], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    const seenOverride = recordRequests('/api/edit/override')

    const { findByRole, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    const checkbox = await findByRole('checkbox', { name: 'keep exactly this window and technique when re-planning' })
    await user.click(checkbox)

    expect(seenOverride).toHaveLength(1)
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'lock', wid: 'w1', locked: true })
  })

  it('handles overrides (changing technique and clearing it)', async () => {
    const planSeg = makePlanSegment({ id: 'w1', locked: false, technique: 'static', options: [{ tech: 'static', score: 1 }, { tech: 'pan', score: 0.5 }] })
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [planSeg], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    let seenOverride = recordRequests('/api/edit/override')
    const { findByRole, findByText, user, unmount } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    const select = await findByRole('combobox', { name: 'chosen by the planner' })
    await user.selectOptions(select, 'pan')
    expect(seenOverride).toHaveLength(1)
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'technique', wid: 'w1', technique: 'pan' })
    unmount()

    const editRespForced = makeEditResponse({ edit: { ...editResp.edit, overrides: { ...editResp.edit.overrides, tech_force: { w1: 'pan' } } as never } })
    mockGet('/api/edit', editRespForced)
    mockPost('/api/edit/override', { edit: editRespForced.edit })
    seenOverride = recordRequests('/api/edit/override')
    const forced = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await forced.findByText('Plan')
    await forced.user.click(await forced.findByRole('button', { name: 'auto' }))
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'technique', wid: 'w1', technique: null })
  })

  it('handles window playback', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment()], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)

    const { findByTitle, findByText, findByRole, queryByRole, user } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')

    const playBtn = await findByTitle('play this window')
    await user.click(playBtn)

    await user.click(await findByRole('button', { name: 'close' }))                                    // the window's player opens over the plan, and closes again
    expect(queryByRole('button', { name: 'close' })).not.toBeInTheDocument()
  })

  it('handles overrides (changing transition)', async () => {
    const planSeg = makePlanSegment({ id: 'w1', index: 1, locked: false, transition: { type: 'cut', beats: 1, dur_s: 0.5, why: 'auto' } })
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [planSeg], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    const seenOverride = recordRequests('/api/edit/override')

    const { findByRole, getByDisplayValue, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    const select = await findByRole('combobox', { name: 'auto' })
    await user.selectOptions(select, 'dissolve')

    expect(seenOverride).toHaveLength(1)
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'transition', wid: 'w1', transition: 'dissolve' })
  })

  it('handles overrides (clearing transition)', async () => {
    const planSeg = makePlanSegment({ id: 'w1', index: 1, locked: false, transition: { type: 'dissolve', beats: 1, dur_s: 0.5, why: 'auto' } })
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {}, transitions: { w1: 'dissolve' } },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [planSeg], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })
    const seenOverride = recordRequests('/api/edit/override')

    const { findByRole, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    await user.click(await findByRole('button', { name: 'auto' }))
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'transition', wid: 'w1', transition: null })
  })

  it('handles clear my changes button', async () => {
    const planSeg = makePlanSegment({ id: 'w1' })
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [{ wid: 'w1' }], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [planSeg], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    const seenOverride = recordRequests('/api/edit/override')

    const { findByRole, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    const btn = await findByRole('button', { name: 'clear my changes' })
    await user.click(btn)

    expect(seenOverride).toHaveLength(1)
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'reset' })
  })

  it('displays orphaned overrides and missing clips warnings', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment()], clips_in_plan: 1, missing_clips: ['CAM_2'], orphaned_overrides: ['w2'], technique_seconds: { static: 5 }, warnings: ['Test warning'] }
      }
    })
    mockGet('/api/edit', editResp)

    const { findByText } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')

    expect(await findByText('1 of your changes no longer match a window and are not applied.', { exact: false })).toBeInTheDocument()
    expect(await findByText('1 clip(s) not in the plan yet (still processing)', { exact: false })).toBeInTheDocument()
    expect(await findByText('Test warning')).toBeInTheDocument()
  })

  it('handles changing clip weight', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment({ clip: 'CAM_1' })], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    const seenOverride = recordRequests('/api/edit/override')

    const { findByRole, findByTitle, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    const btn = await findByTitle('more of this clip')
    await user.click(btn)

    expect(seenOverride).toHaveLength(1)
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'weight', clip: 'CAM_1', factor: 1.5 })
  })

  it('handles changing clip weight (less)', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment({ clip: 'CAM_1' })], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    const seenOverride = recordRequests('/api/edit/override')

    const { findByTitle, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    const btn = await findByTitle('less of this clip')
    await user.click(btn)

    expect(seenOverride).toHaveLength(1)
    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'weight', clip: 'CAM_1', factor: 1 / 1.5 })
  })

  it('handles skip moment', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment({ clip: 'CAM_1', clip_start_s: 0, dur_s: 5 })], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    mockPost('/api/edit/override', { edit: editResp.edit })

    const seenOverride = recordRequests('/api/edit/override')

    const { findByTitle, findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} onOpenClip={vi.fn()} />)
    await findByText('Plan')
    await user.click(await findByTitle('never use this footage (whichever way of seeing it)'))

    expect(seenOverride[0].body).toEqual({ folder: '/data', action: 'ban', kind: 'moment', key: 'win:CAM_1@0@5', on: true })
  })

  it('labels the windows of a plan made from the script: you, narration, b-roll', async () => {
    const seg = (id: string, role: 'clip' | 'vo' | 'broll', i: number) => makePlanSegment({ id, clip: 'CAM_1', role, item: i, index: i, film_start_s: i * 5, options: [{ tech: 'static', score: 1 }] })
    mockGet('/api/edit', makeEditResponse({ edit: {
      settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' }, overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
      plan: { source: 'script', script: 'draft-1.json', generated_at: 'utc', film: { length_s: 15, beats: 30, bpm: 120 }, segments: [seg('a', 'clip', 0), seg('b', 'vo', 1), seg('c', 'broll', 2)], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 15 }, warnings: [] } } }))
    const { findByText, getByText } = setup(<Timeline folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} onOpenClip={vi.fn()} />)
    expect(await findByText(/from the script draft/)).toBeInTheDocument()
    expect(getByText('you')).toBeInTheDocument(); expect(getByText('narration')).toBeInTheDocument(); expect(getByText('b-roll')).toBeInTheDocument()
  })

  it('calls onOpenClip when a clip name is clicked', async () => {
    const onOpenClip = vi.fn()
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment({ clip: 'CAM_1' })], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)
    const { findByText, user } = setup(<Timeline folder="/data" clips={[makeClipInfo({ id: 'CAM_1' })]} onOpenClip={onOpenClip} />)
    await user.click(await findByText('1'))
    expect(onOpenClip).toHaveBeenCalledWith('CAM_1')
  })

  describe('timeline editing (D1)', () => {
    // A 30 s film at 120 bpm (0.5 s a beat) in three windows; the strip is 600 px wide, so a beat is 10 px.
    const seg3 = () => [
      makePlanSegment({ id: 'a', clip: 'CAM_1', film_start_s: 0, dur_s: 10, beats: 20, clip_start_s: 0, edge_room: [-4, 3], pos: { lat: 50.1, lon: 5.1, km: 1 } }),
      makePlanSegment({ id: 'b', clip: 'CAM_1', film_start_s: 10, dur_s: 10, beats: 20, clip_start_s: 30, edge_room: [-2, 6], pos: { lat: 50.2, lon: 5.2, km: 2 } }),
      makePlanSegment({ id: 'c', clip: 'CAM_2', film_start_s: 20, dur_s: 10, beats: 20, clip_start_s: 5, locked: true, pos: { lat: 50.3, lon: 5.3, km: 3.5 } }),
    ]
    const film = (o: Record<string, unknown> = {}) => makeEditResponse({ edit: makeEditState({ history: 0, ...o, plan: { generated_at: 'utc', film: { length_s: 30, beats: 60, bpm: 120 }, segments: seg3(), clips_in_plan: 2, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 30 }, warnings: [], ...((o.plan as object) ?? {}) } as never }) })
    let unRect: () => void
    beforeEach(() => { stubBrowserApis(); unRect = stubRect(600, 36) })
    afterEach(() => unRect())

    it('drags a cut and sends the move snapped to whole beats', async () => {
      mockGet('/api/edit', film()); mockPost('/api/edit/override', { edit: film().edit }); const seen = recordRequests('/api/edit/override')
      const { findAllByRole, findByText } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      const [cut] = await findAllByRole('separator')
      fireEvent.pointerDown(cut, { clientX: 300 }); fireEvent.pointerMove(window, { clientX: 324 })        // 2.4 beats later: snaps to 2
      expect(await findByText('+2 beats')).toBeInTheDocument()
      fireEvent.pointerUp(window, { clientX: 324 })
      await vi.waitFor(() => expect(seen).toHaveLength(1))
      expect(seen[0].body).toEqual({ folder: '/data', action: 'edge', wid: 'a', beats: 2 })
    })

    it('keeps a dragged cut inside the room the server gives it', async () => {
      mockGet('/api/edit', film()); const seen = recordRequests('/api/edit/override')
      const { findAllByRole, findByText } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      const [cut] = await findAllByRole('separator')
      fireEvent.pointerDown(cut, { clientX: 300 }); fireEvent.pointerMove(window, { clientX: 100 })         // 20 beats earlier, but it has room for 4
      expect(await findByText('-4 beats')).toBeInTheDocument()
      fireEvent.pointerUp(window, {}); await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ action: 'edge', wid: 'a', beats: -4 })
    })

    it('sends nothing for a drag of less than half a beat', async () => {
      mockGet('/api/edit', film()); const seen = recordRequests('/api/edit/override')
      const { findAllByRole } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      const [cut] = await findAllByRole('separator')
      fireEvent.pointerDown(cut, { clientX: 300 }); fireEvent.pointerMove(window, { clientX: 304 }); fireEvent.pointerUp(window, {})
      await new Promise(r => setTimeout(r, 20)); expect(seen).toHaveLength(0)
    })

    it('shows why the server snapped the cut somewhere else', async () => {
      mockGet('/api/edit', film()); mockPost('/api/edit/override', { edit: film().edit, note: { asked: 3, beats: 1, why: 'moved 1 beat, not 3: the nearest beat that does not cut into the words' } })
      const { findAllByRole, findByText, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      const [cut] = await findAllByRole('separator'); cut.focus(); await user.keyboard('{ArrowRight}')
      expect(await findByText(/does not cut into the words/)).toBeInTheDocument()
    })

    it('moves a focused cut by one beat with the arrow keys, and only where it has room', async () => {
      mockGet('/api/edit', film()); const seen = recordRequests('/api/edit/override')
      const { findAllByRole, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      const cuts = await findAllByRole('separator'); expect(cuts).toHaveLength(2)
      cuts[1].focus(); await user.keyboard('{ArrowLeft}')
      await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ action: 'edge', wid: 'b', beats: -1 })
    })

    it('asks for one window, then a shift-clicked run, to be suggested again', async () => {
      mockGet('/api/edit', film()); const seen = recordRequests('/api/edit/override')
      const { findByRole, getByRole, getByTitle, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      expect(await findByRole('button', { name: 'Suggest again' })).toBeDisabled()
      await user.click(getByTitle(/^0:10.0 1 static/)); await user.click(getByRole('button', { name: 'Suggest again' }))
      await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', action: 'suggest', wids: ['b'] })
      await user.click(getByTitle(/^0:00.0 1 static/)); await user.keyboard('{Shift>}'); await user.click(getByTitle(/^0:20.0 2 static/)); await user.keyboard('{/Shift}')
      await user.click(await findByRole('button', { name: 'Suggest again (3 windows)' }))
      await vi.waitFor(() => expect(seen).toHaveLength(2)); expect(seen[1].body).toEqual({ folder: '/data', action: 'suggest', wids: ['a', 'b', 'c'] })
    })

    it('cannot suggest a locked window again', async () => {
      mockGet('/api/edit', film())
      const { findByTitle, getByRole, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      await user.click(await findByTitle(/^0:20.0 2 static/)); expect(getByRole('button', { name: 'Suggest again' })).toBeDisabled()
    })

    it('steps back to an earlier version when there is one', async () => {
      mockGet('/api/edit', film({ history: 2 })); const seen = recordRequests('/api/edit/override')
      const { findByRole, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      await user.click(await findByRole('button', { name: 'Step back (2)' }))
      await vi.waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', action: 'back' })
    })

    it('shows the server\'s reason when a suggestion is not possible', async () => {
      mockGet('/api/edit', film()); mockError('/api/edit/override', 400, 'there is no other footage between the windows either side of this part of the film', 'post')
      const { findByTitle, getByRole, findByText, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      await user.click(await findByTitle(/^0:00.0 1 static/)); await user.click(getByRole('button', { name: 'Suggest again' }))
      expect(await findByText(/no other footage/)).toBeInTheDocument()
    })

    it('offers no dragging or suggestions for a film planned from the script', async () => {
      mockGet('/api/edit', film({ plan: { source: 'script' } }))
      const { findByText, queryAllByRole, queryByRole } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      expect(await findByText(/change it in the Film script panel/)).toBeInTheDocument()
      expect(queryAllByRole('separator')).toHaveLength(0); expect(queryByRole('button', { name: 'Suggest again' })).toBeNull()
    })

    it('draws each window on the map strip and selects it from there', async () => {
      mockGet('/api/edit', film())
      const { findByRole, getByRole, user } = setup(<Timeline folder="/data" clips={[]} onOpenClip={vi.fn()} />)
      const map = await findByRole('img', { name: 'Where each window of the film was filmed' })
      await vi.waitFor(() => expect(map.querySelector('polyline')).not.toBeNull())
      const dots = map.querySelectorAll('circle'); expect(dots).toHaveLength(3); expect(dots[2].textContent).toBe('0:20.0 2 · km 3.5')
      await user.click(dots[0] as Element); expect(getByRole('button', { name: 'Suggest again' })).toBeEnabled()
    })
  })
})
