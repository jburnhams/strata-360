import type { Browse, BrowseEntry, Notes, Progress, StateMatrix, Seg, ClipInfo, WordT, StageHealth, Meta, ClockState, TrackOverview, WhoState, MusicState } from '../../src/api'

// Typed builders for API payloads: sensible defaults, override what the test cares about (`makeBrowse({ can_create: false })`).
// Add one per interface in src/api.ts as tests need it. Keep the defaults boring and valid.
export const makeBrowseEntry = (o: Partial<BrowseEntry> = {}): BrowseEntry => ({ name: 'trip', path: '/data/trip', kind: 'dir', is_project: false, ...o })

export const makeWordT = (o: Partial<WordT> = {}): WordT => ({ w: 'hello', t0: 0, t1: 1, ...o })

export const makeSeg = (o: Partial<Seg> = {}): Seg => ({ si: 0, clip: 'CAM_123', t0: 0, t1: 1, lang: 'en', text: 'hello', text_en: null, flagged: false, who: 'wearer', words: [makeWordT()], ...o })

export const makeClipInfo = (o: Partial<ClipInfo> = {}): ClipInfo => ({ id: 'CAM_123', start_utc: '2023-01-01T12:00:00Z', duration_s: 10, has_note: false, thumb: 'best', steady: 1, candidates: 2, ...o })

export const makeTranscriptFix = (o: Partial<{ usage?: { calls: number; input: number; output: number; paid_calls: number; cost_usd: number }; health?: StageHealth | null; calls_made?: number; calls_reused?: number; tokens?: { input: number; output: number }; state: string; done?: number; total?: number; fixes?: number; error?: string }> = {}) => ({ state: 'done', ...o })

export const makeBrowse = (o: Partial<Browse> = {}): Browse => ({ path: '/data', parent: null, footage_here: 0, is_project: false, can_create: false, entries: [], ...o })

export const makeNotes = (o: Partial<Notes> = {}): Notes => ({ folder: '', clips: {}, updated: {}, ...o })

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
