import type { Browse, BrowseEntry, Notes, Progress, StateMatrix, Seg, ClipInfo, WordT, StageHealth, Meta, ClockState, TrackOverview, WhoState, MusicState, Gap, GapClip, FilmState, FinalState } from '../../src/api'

// Typed builders for API payloads: sensible defaults, override what the test cares about (`makeBrowse({ can_create: false })`).
// Add one per interface in src/api.ts as tests need it. Keep the defaults boring and valid.
export const makeBrowseEntry = (o: Partial<BrowseEntry> = {}): BrowseEntry => ({ name: 'trip', path: '/data/trip', kind: 'dir', is_project: false, ...o })

export const makeWordT = (o: Partial<WordT> = {}): WordT => ({ w: 'hello', t0: 0, t1: 1, ...o })

export const makeSeg = (o: Partial<Seg> = {}): Seg => ({ si: 0, clip: 'CAM_123', t0: 0, t1: 1, lang: 'en', text: 'hello', text_en: null, flagged: false, who: 'wearer', words: [makeWordT()], ...o })

export const makeClipInfo = (o: Partial<ClipInfo> = {}): ClipInfo => ({ id: 'CAM_123', start_utc: '2023-01-01T12:00:00Z', duration_s: 10, has_note: false, thumb: 'best', steady: 1, candidates: 2, ...o })

export const makeTranscriptFix = (o: Partial<{ usage?: { calls: number; input: number; output: number; paid_calls: number; cost_usd: number }; health?: StageHealth | null; calls_made?: number; calls_reused?: number; tokens?: { input: number; output: number }; state: string; done?: number; total?: number; fixes?: number; error?: string }> = {}) => ({ state: 'done', ...o })

export const makeBrowse = (o: Partial<Browse> = {}): Browse => ({ path: '/data', parent: null, footage_here: 0, is_project: false, can_create: false, entries: [], ...o })

export const makeNotes = (o: Partial<Notes> = {}): Notes => ({ folder: '', clips: {}, updated: {}, vo_must: { folder: '', folder_ordered: true, clips: {} }, ...o })

export const makeProgress = (o: Partial<Progress> = {}): Progress => ({ state: 'new', folder: '/data', project: 'test', job_running: false, ...o })

export const makeStateMatrix = (o: Partial<StateMatrix> = {}): StateMatrix => ({ stages: [], clips: {}, dependents: {}, ...o })

export const makeMeta = (o: Partial<Meta> = {}): Meta => ({ timezone: 'Europe/Brussels', title: 'Test Title', date: '2023-01-01', results: { starters: null, finishers: null, finished: null, position: null }, defaults: { title: null, date: null, earliest_capture_utc: null }, effective: { title: null, date: null }, ...o })

export const makeClockState = (o: Partial<ClockState> = {}): ClockState => ({ offset_s: 0, verified: false, note: null, anchors: [], has_track: false, ...o })

export const makeTrackOverview = (o: Partial<TrackOverview> = {}): TrackOverview => ({ present: false, ...o })

export const makeWhoState = (o: Partial<WhoState> = {}): WhoState => ({ ready: true, profile: false, ...o })
export const makeMusicState = (o: Partial<MusicState> = {}): MusicState => ({ file: null, analysis: null, ...o })
export const makePlanSegment = (o: Partial<import('../../src/api').PlanSegment> = {}): import('../../src/api').PlanSegment => ({ id: 'w1', index: 0, clip: 'CAM_123', cand_id: 'c1', film_start_s: 0, beats: 4, dur_s: 5, clip_start_s: 10, utc_start: 'utc', utc_end: 'utc', technique: 'static', family: 'static', hero: true, forced: false, speech: false, locked: false, options: [{ tech: 'static', score: 1 }], ...o })
export const makeEditState = (o: Partial<import('../../src/api').EditState> = {}): import('../../src/api').EditState => ({ settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' }, overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} }, plan: null, ...o })
export const makeEditResponse = (o: Partial<import('../../src/api').EditResponse> = {}): import('../../src/api').EditResponse => ({ edit: makeEditState(), techniques: [], script: {}, ...o })
export const makeScriptLine = (o: Partial<import('../../src/api').ScriptLine> = {}): import('../../src/api').ScriptLine => ({ seg: 1, film_start_s: 0, seconds: 5, clip: 'CAM_1', text: 'Hello', words: 1, est_speak_s: 1, budget_words: 10, ...o })
export const makeScriptDoc = (o: Partial<import('../../src/api').ScriptDoc> = {}): import('../../src/api').ScriptDoc => ({ file: 'script.json', title: 'Script', target_s: 60, wpm: 150, lines: [makeScriptLine()], total_words: 1, total_speak_s: 1, remaining_problems: [], ...o })
export const makeScriptState = (o: Partial<import('../../src/api').ScriptState> = {}): import('../../src/api').ScriptState => ({ key_configured: true, providers: { vertex: { models: ['gemini-1.5-pro'], default: 'gemini-1.5-pro', configured: true } }, models: [], llm: { provider: 'vertex', model: 'gemini-1.5-pro' }, running: false, last_exit: null, log: '', latest: null, scripts: 0, ...o })
export const makeVoiceLine = (o: Partial<import('../../src/api').VoiceLine> = {}): import('../../src/api').VoiceLine => ({ seg: 1, text: 'Hello', source: 'synth', has_recording: false, film_start_s: 0, window_s: 5, room_s: 5, natural_s: 2, played_s: 2, overrun_s: 0, tempo: 1, fit: 'ok', synth_s: 2, ...o })
export const makeVoiceoverState = (o: Partial<import('../../src/api').VoiceoverState> = {}): import('../../src/api').VoiceoverState => ({ engines: [{ id: 'k', label: 'koko', voices: [{ name: 'v1', lang: 'en' }] }], state: { engine: 'k', voice: 'v1', rate: 1, use: {} }, timings: null, script: null, lines: 1, building: false, ...o })
export const makeClipDetail = (o: Partial<import('../../src/api').ClipDetail> = {}): import('../../src/api').ClipDetail => ({ id: 'CAM_1', note: '', time: { start_utc: '2023-01-01T12:00:00Z' }, video: { source_frames: 300, nominal_fps: 30 }, motion: { steady: 0.9, median_shake_dps: 1.5, total_turn_deg: 90 }, audio: null, transcript: [], scenes: null, identity: null, candidates: [], exposure: null, thumb: null, places: { covered: true, points: [{ label: 'p1', lat: 0, lon: 0, address: { display_name: 'Place' }, nearby: [] }] }, ...o })

export const makeScript2State = (o: Partial<import('../../src/api').Script2State> = {}): import('../../src/api').Script2State => ({ draft: null, drafts: [], pins: {}, running: false, last_exit: null, log: [], used: [], key_configured: true, ...o })

export const makeScriptDraft = (o: Partial<import('../../src/api').ScriptDraft> = {}): import('../../src/api').ScriptDraft => ({
  title: 'A Film', story: 'It starts, it gets hard, it ends.', skipped: [], problems: [], warnings: [], created: '2026-10-02T01:00:00', target_s: 60, target_source: 'music', wpm: 170, model: 'gemini-3.1-pro-preview', revised: false, draft_of: null,
  report: { total_s: 61.2, target_s: 60, vo_s: 8, clip_s: 40, broll_s: 13.2, vo_words: 22, clips_used: 2, clips_skipped: 0 },
  items: [
    { type: 'vo', clip: '0023', text: 'It is Sunday afternoon.', basis: ['Sun 22 Feb 14:04'], seconds: 4 },
    { type: 'clip', clip: '0023', from: '0023.00', to: '0023.00', lines: ['0023.00'], text: 'we are fine', seconds: 3.2, refs: [{ clip: 'CAM_20260222130830_0023_D', si: 0, w0: 0, w1: 3 }] },
    { type: 'broll', clip: '0024', seconds: 5, why: 'a foggy trail' },
  ], ...o })

export const makeTrackLine = (o: Partial<import('../../src/api').TrackLine> = {}): import('../../src/api').TrackLine => {
  const n = 20; return { lat: Array.from({ length: n }, (_, i) => 50 + i * 0.01), lon: Array.from({ length: n }, (_, i) => 5 + i * 0.015), t: Array.from({ length: n }, (_, i) => i * 400), ...o }
}
export const makeTrackSeries = (o: Partial<import('../../src/api').TrackSeries> = {}): import('../../src/api').TrackSeries => {
  const n = 40; return {
    points: n, start_utc: '2026-02-22T18:00:00Z', end_utc: '2026-02-23T04:00:00Z', duration_s: 36000, distance_km: 75.6,
    t: Array.from({ length: n }, (_, i) => i * 900), km: Array.from({ length: n }, (_, i) => i * 2), alt: Array.from({ length: n }, (_, i) => 300 + 100 * Math.sin(i / 5)), alt_lo: Array.from({ length: n }, (_, i) => 290 + 100 * Math.sin(i / 5)), alt_hi: Array.from({ length: n }, (_, i) => 310 + 100 * Math.sin(i / 5)),
    pace: Array.from({ length: n }, (_, i) => (i >= 12 && i < 16 ? null : 5.5 + (i % 7) * 0.4)), moving: Array.from({ length: n }, (_, i) => (i >= 12 && i < 16 ? 0 : 1)), hr: Array.from({ length: n }, () => 140), ...o }
}
export const makeTrackClip = (o: Partial<import('../../src/api').TrackClip> = {}): import('../../src/api').TrackClip => ({
  id: 'CAM_20260222190000_0023_D', label: '0023', start_utc: '2026-02-22T19:00:00Z', end_utc: '2026-02-22T19:03:35Z', duration_s: 215, covered: true, used: true, used_s: 16.5, moments: 7, usable_s: 117, scene: { settings: ['trail'], weather: ['fog'] },
  t_mid: 3600, t0: 3500, t1: 3700, lat: 50.09, lon: 5.135, stretch: [[50.089, 5.134], [50.091, 5.136]],
  facts: { local: 'Sun 22 Feb 20:01', daylight: 'night', elapsed_h: 1.0, distance_km: 12.3, percent: 16, pace_min_km: 5.75, gradient_pct: 4, altitude_m: 569, heart_rate: 141, text: 'x' }, ...o })

export const makeGapClip = (o: Partial<GapClip> = {}): GapClip => ({ id: 'G01', gap: 'G01', kind: 'map', t0: '2026-02-19T17:17:00Z', t1: '2026-02-19T20:47:00Z', duration_s: 12600, seconds: 14, speedup: 900, status: 'planned', rendering: false, progress: '', exists: false, ...o })
export const makeGap = (o: Partial<Gap> = {}): Gap => ({
  id: 'G01', t0: 1771521420, t1: 1771534020, duration_s: 12600, local_start: 'Thu 19 Feb 18:17', local_end: 'Thu 19 Feb 21:47', km_start: 2.5, km_end: 27, distance_km: 24.5, moving_share: 0.99, ascent_m: 860,
  daylight: 'twilight->night', before: 'a', after: 'b', default_seconds: 14, clips: [], ...o,
})
export const makeFilmState = (o: Partial<FilmState> = {}): FilmState => ({ state: 'none', running: false, ...o })
export const makeFinalState = (o: Partial<FinalState> = {}): FinalState => ({ state: 'none', running: false, settings: { size: '1080p', fps: 30, bitrate: '20M' }, ...o })
