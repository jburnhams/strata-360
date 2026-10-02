import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { setup } from '../utils/render'
import Timeline from '../../src/components/Timeline'
import { makeClipInfo, makeEditResponse, makePlanSegment } from '../utils/factories'
import { mockGet, mockPost, mockError, mockPending, recordRequests } from '../utils/api'
import { stubMedia } from '../utils/media'

vi.mock('../../src/components/FilmPreview', () => ({ default: () => <div data-testid="film-preview" /> }))
vi.mock('../../src/components/FinalRender', () => ({ default: () => <div data-testid="final-render" /> }))
vi.mock('../../src/components/MusicPanel', () => ({ default: () => <div data-testid="music-panel" /> }))
vi.mock('../../src/components/WindowPlayer', () => ({ default: () => <div data-testid="window-player" /> }))

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
    expect(seenPropose[0].body).toEqual({ folder: '/data', length_s: 90, bpm: 120, keep: true })
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

  it('handles window playback', async () => {
    const editResp = makeEditResponse({
      edit: {
        settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' },
        overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} },
        plan: { generated_at: 'utc', film: { length_s: 5, beats: 10, bpm: 120 }, segments: [makePlanSegment()], clips_in_plan: 1, missing_clips: [], orphaned_overrides: [], technique_seconds: { static: 5 }, warnings: [] }
      }
    })
    mockGet('/api/edit', editResp)

    const { findByTitle, findByText, getByTestId, user } = setup(<Timeline folder="/data" clips={[makeClipInfo()]} onOpenClip={vi.fn()} />)
    await findByText('Plan')

    const playBtn = await findByTitle('play this window')
    await user.click(playBtn)

    expect(getByTestId('window-player')).toBeInTheDocument()
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
})
