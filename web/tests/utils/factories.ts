import type { Browse, BrowseEntry, Notes, Progress, StateMatrix, Seg, ClipInfo, WordT, StageHealth, Meta, ClockState, TrackOverview, WhoState } from '../../src/api'

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
