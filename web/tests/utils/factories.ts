import type { Browse, BrowseEntry, Notes, Progress, StateMatrix, Seg, ClipInfo, WordT, StageHealth, Meta, ClockState, TrackOverview, WhoState, MusicState, Gap, GapClip, FilmState, FinalState, RoughMix, Lyrics, LyricPhrase, DetectedObject, Region, ObjectsInfo } from '../../src/api'

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
import type { StudioGrid, StudioPreview, StudioState, MusicScore } from '../../src/api'
export const makeStudioGrid = (o: Partial<StudioGrid> = {}): StudioGrid => ({ bpm: 120, key: { tonic: 9, mode: 'minor', name: 'A minor', confidence: 0.8 }, bars: 8, duration_s: 16, bar_s: 2, downbeats: [0, 2, 4, 6, 8, 10, 12, 14, 16], energy: [0.2, 0.2, 0.5, 0.5, 0.8, 0.8, 0.3, 0.3], ...o })
export const makeMusicScore = (o: Partial<MusicScore> = {}): MusicScore => ({ source: 'built', file: 'music/built.flac', of: 'music/track.mp3', length_s: 40, bpm: 120, key: makeStudioGrid().key, bars: [0, 1, 2, 3, 4, 3, 4, 6, 7], runs: [[0, 5], [3, 2], [6, 2]], joins: [0.05], worst_join: 0.05, downbeats: [], levels: null, windows: [], stray_vocal_db: null, ...o })
export const makeScorePlan = (o: Partial<import('../../src/api').ScorePlan> = {}): import('../../src/api').ScorePlan => ({ fidelity: 0.75, share_original: 0.5, unreachable: [], sung: [],
  sections: [{ first: 0, end: 4, level: 0.9, source: 'original', mismatch: 0.1, pinned: false, sung: false, key: 'a1', new: false }, { first: 4, end: 8, level: 0.15, source: 'generate', mismatch: 0.5, pinned: false, sung: false, strength: 0.65, repaint: true, key: 'b2', new: true }], ...o })
export const makeStudioState = (o: Partial<StudioState> = {}): StudioState => ({ grid: makeStudioGrid(), built: null, stems: false, building: false, error: '', log: '', ...o })
export const makeStudioPreview = (o: Partial<StudioPreview> = {}): StudioPreview => ({ bars: 8, bar_s: 2, length_s: 16, levels: [0.9, 0.9, 0.9, 0.9, 0.4, 0.4, 0.4, 0.4], windows: [], plan: { bars: [0, 1, 2, 3, 2, 3, 6, 7], runs: [[0, 4], [2, 2], [6, 2]], joins: [0.04, 0.3], worst_join: 0.3 },
  gains: { drums: [1, 1, 1, 1, 0, 0, 0, 0], bass: [1, 1, 1, 1, 1, 1, 1, 1], other: [1, 1, 1, 1, 0.8, 0.8, 0.8, 0.8], vocals: [0, 0, 0, 0, 0, 0, 0, 0] }, sim: Array.from({ length: 8 }, (_, i) => Array.from({ length: 8 }, (_, j) => (i === j ? 1 : 0.4))), energy: [0.2, 0.2, 0.5, 0.5, 0.8, 0.8, 0.3, 0.3], ...o })
export const makePlanSegment = (o: Partial<import('../../src/api').PlanSegment> = {}): import('../../src/api').PlanSegment => ({ id: 'w1', index: 0, clip: 'CAM_123', cand_id: 'c1', film_start_s: 0, beats: 4, dur_s: 5, clip_start_s: 10, utc_start: 'utc', utc_end: 'utc', technique: 'static', family: 'static', hero: true, forced: false, speech: false, locked: false, options: [{ tech: 'static', score: 1 }], ...o })
export const makeEditState = (o: Partial<import('../../src/api').EditState> = {}): import('../../src/api').EditState => ({ settings: { length_s: 90, bpm: 120, bar_beats: 4, seed: 1, wpm: 150, style: 'default' }, overrides: { locked: [], tech_force: {}, bans_cands: [], bans_techs: [], clip_weight: {} }, plan: null, ...o })
export const makeEditResponse = (o: Partial<import('../../src/api').EditResponse> = {}): import('../../src/api').EditResponse => ({ edit: makeEditState(), techniques: [], script: {}, ...o })

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
export const makePhoto = (o: Partial<import('../../src/api').Photo> = {}): import('../../src/api').Photo => ({
  id: 'p1', name: 'IMG_0001.jpg', taken_utc: 1_771_700_000, time_source: 'gps clock', width: 4000, height: 3000, camera: 'Phone', gps: { lat: 50.1, lon: 5.1 }, track: { lat: 50.1, lon: 5.1, elapsed_s: 4325, km: 12.1 },
  loc: { lat: 50.1, lon: 5.1, source: 'photo gps' }, apart_m: 25, flag: null, where: { kind: 'clip', id: 'CAM_20260222190000_0023_D' }, ...o })
export const makeTracksListing = (o: Partial<import('../../src/api').TracksListing> = {}): import('../../src/api').TracksListing => ({ tracks: [], merged: null, pois: [], runs: 0, ...o })
export const makeTrackEntry = (o: Partial<import('../../src/api').TrackEntry> = {}): import('../../src/api').TrackEntry => ({ id: 't1', name: 'race.gpx', kind: 'run', samples: 100, timed: true, start_utc: '2026-02-22T18:00:00Z', end_utc: '2026-02-23T04:00:00Z', distance_km: 75.6, pois: 0, ...o })
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
export const makeRoughMix = (o: Partial<RoughMix> = {}): RoughMix => ({ has_plan: true, exists: false, stale: false, stale_because: [], length_s: null, made_at: null, source: 'script', building: false, error: '', log: '', ...o })
export const makeScriptState = (o: Partial<import('../../src/api').ScriptState> = {}): import('../../src/api').ScriptState => ({ key_configured: true, providers: { anthropic: { models: ['claude-3'], default: 'claude-3', configured: true } }, models: ['claude-3'], llm: { provider: 'anthropic', model: 'claude-3' }, running: false, last_exit: null, log: '', latest: null, scripts: 0, ...o })
export const makeVoiceoverState = (o: Partial<import('../../src/api').VoiceoverState> = {}): import('../../src/api').VoiceoverState => ({ engines: [{ id: 'e1', label: 'Engine 1', voices: [{ name: 'v1', lang: 'en' }] }], state: { engine: 'e1', voice: 'v1', rate: 100, use: {} }, timings: null, script: null, cached: [], lines: 0, building: false, error: null, ...o })
export const makeLyricPhrase = (o: Partial<LyricPhrase> = {}): LyricPhrase => ({ key: '100.0-103.0', id: 'L01', t0: 100, t1: 103, text: 'line one', heard: 'line one', conf: 0.6, doubtful: false, deleted: false, edited: false, counts: true, ...o })
export const makeLyrics = (o: Partial<Lyrics> = {}): Lyrics => ({ has_track: true, exists: false, stale: false, instrumental: false, phrases: 0, sung_s: null, duration_s: null, made_at: null, language: null, building: false, error: '', log: '', phrases_list: [], vocal_spans: [], ...o })

export const makeSvSection = (o: Partial<import('../../src/api').SvSectionInfo> = {}): import('../../src/api').SvSectionInfo => ({
  id: 'M1', key: 'mapillary:s1:1.20', plausible: true, why_not: '', play_s: 2.7, min_s: 2, max_s: 1, speed_ms: 100, label: null, overlaps: [], choice: null, near: null, filmed: [1_709_812_800, 1_709_812_830], passed: [1_771_754_460, 1_771_754_520], has_video: false, quality: null, light: null, steadied: 'by matching only',
  provider: 'mapillary', stretch: 'R1', kind: '2d', km0: 1.2, km1: 1.5, length_m: 300, frames: 4, spacing_m: 100, years: [2024], camera: 'GoPro HERO7 Black', size: [4000, 3000], seq: 's1', angles: { forward: 3, back: 1 },
  items: [{ id: 'm1', km: 1.2, lat: 50.001, lon: 5.001, a: 0, b: 90 }, { id: 'm2', km: 1.3, lat: 50.001, lon: 5.002, a: 10, b: 90 }, { id: 'm3', km: 1.4, lat: 50.001, lon: 5.003, a: -20, b: 90 }, { id: 'm4', km: 1.5, lat: 50.001, lon: 5.004, a: 170, b: 90 }], ...o })
export const makeStreetView = (o: Partial<import('../../src/api').StreetView> = {}): import('../../src/api').StreetView => ({
  status: { roads: { done: true, stretches: 2, km: 1.1 }, mapillary: { done: true, stale: false, sections: 2, frames: 9, km: 0.5 }, panoramax: { done: false, km: 0 }, google: { done: false, km: 0 }, quality: { done: false, km: 0 } },
  roads: { id: 'r1', total_km: 3, run: [[50.0, 5.0], [50.001, 5.005]], stretches: [{ id: 'R1', km0: 1.0, km1: 1.6, length_m: 600, highways: ['residential'], names: ['Rue A'], line: [[50.001, 5.0], [50.001, 5.005]] }, { id: 'R2', km0: 2.0, km1: 2.5, length_m: 500, highways: ['secondary'], names: [], line: [[50.002, 5.0], [50.002, 5.004]] }] },
  providers: { mapillary: { frames: 9, km: 0.5 }, panoramax: null, google: null },
  sections: [makeSvSection(), makeSvSection({ id: 'M2', key: 'mapillary:s2:2.10', kind: '360', angles: null, km0: 2.1, km1: 2.3, length_m: 200, frames: 5, spacing_m: 8, size: [5760, 2880], camera: 'GoPro Max', stretch: 'R2', plausible: false, why_not: 'only 5 pictures (needs 30)',
    items: [{ id: 'q1', km: 2.1, lat: 50.002, lon: 5.001, b: 90 }, { id: 'q2', km: 2.2, lat: 50.002, lon: 5.002, b: 90 }] })],
  job: { running: false, log: [], error: '' }, keys: { mapillary: true, google: false }, ...o })

export const makeNearItem = (o: Partial<import('../../src/api').SvNearItem> = {}): import('../../src/api').SvNearItem => ({
  provider: 'mapillary', id: 'm9', sequence: 's9', lat: 50.0015, lon: 5.0015, distance_m: 12.5, kind: '360', camera: 'GoPro Max', size: [5760, 2880], captured: 1_709_812_800, compass: 10, pictures: 27, spacing_m: 4.7, section: null, run_distance_m: 12, run_km: 140.08, passed: 1_771_754_460,
  rules: [{ key: 'near_run', ok: true, text: "12 m from the run's track (pictures count within 12 m)" }, { key: 'light', ok: false, text: 'Filmed with the sun 6° above the horizon (golden-hour light), but the runner passes here with the sun 10° below the horizon (dark): it would look wrong in the film.' }, { key: 'direction', ok: null, text: 'the way the camera faced is not known' }],
  usable: false, ruled_out: ['Filmed with the sun 6° above the horizon (golden-hour light), but the runner passes here with the sun 10° below the horizon (dark): it would look wrong in the film.'], ...o })
export const makeNearResult = (o: Partial<import('../../src/api').SvNearResult> = {}): import('../../src/api').SvNearResult => ({
  lat: 50.0, lon: 5.0, n: 5, providers: { mapillary: { items: [makeNearItem()], radius_m: 100 }, panoramax: { items: [], radius_m: 500 }, google: { items: [], radius_m: null, error: 'no GOOGLE_MAPS_API_KEY in secrets.env' } }, ...o })

export const makePointCam = (o: Partial<import('../../src/api').PointCam> = {}): import('../../src/api').PointCam => ({
  id: 'C1', label: 'C1', source: { kind: 'clip', clip: 'CAM_1_0001_D' }, lat: 50.01, lon: 5.01, height_m: 0, before_m: 40, after_m: 40, fov_near: 95, fov_far: 55, smooth_s: 0.8, use: '', t_pass: 1_771_700_100, seconds: null, name: null, script: [], ok: true,
  facts: { seconds: 26.7, min_dist_m: 30, max_dist_m: 62, max_pan_deg_s: 24, swing_deg: 140, fov_min: 70, fov_max: 95, warnings: [] }, source_seconds: 26.7, range: [2, 26.7], window: [1_771_700_087, 1_771_700_114],
  geometry: { line: [[50.0, 5.0], [50.01, 5.0], [50.02, 5.0]], sights: [{ at: [50.0, 5.0], bearing: 20, fov: 55, dist: 60, t: 1_771_700_087 }, { at: [50.02, 5.0], bearing: 200, fov: 95, dist: 30, t: 1_771_700_114 }], at: [50.01, 5.0] }, ...o,
})
export const makePointCams = (cams: import('../../src/api').PointCam[] = [], o: Partial<import('../../src/api').PointCams> = {}): import('../../src/api').PointCams => ({
  cams, limits: { height_m: [0, 300], before_m: [5, 400], after_m: [5, 400], fov_near: [30, 130], fov_far: [20, 130], smooth_s: [0, 4] }, defaults: { height_m: 0, before_m: 40, after_m: 40, fov_near: 95, fov_far: 55, smooth_s: 0.8, use: '' }, ...o,
})

export const makeObject = (o: Partial<DetectedObject> = {}): DetectedObject => ({ id: 0, label: 'goat', word: 'goat', kind: 'named', source: 'vlm', yoloe: 'cow', conf: 0.8, lon: -90, lat: -5, deg: 4, best_t: 1, seen: [1, 8.5], crop: true, ...o })
export const makeRegion = (o: Partial<Region> = {}): Region => ({ kind: 'snow', lon: 40, lat: -30, w_deg: 30, h_deg: 10, polygon: [[25, -25], [55, -25], [55, -35], [25, -35]], seen: [1], n: 2, ...o })
export const makeObjects = (o: Partial<ObjectsInfo> = {}): ObjectsInfo => ({ skipped: null, model: 'Qwen3.5', moments: 4, objects: [makeObject()], regions: [], areas: {}, scenery_labels: {}, counts: {}, ...o })
