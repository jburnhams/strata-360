// Typed client for the FastAPI server (src/strata360/server/app.py). Same-origin; the token (if any) travels as a cookie.
export interface BrowseEntry { name: string; path: string; kind: 'dir'; is_project: boolean }
export interface Browse { path: string; parent: string | null; footage_here: number; is_project: boolean; can_create: boolean; entries: BrowseEntry[] }
export interface StageHealth { retrying: number; failed: number; attempts: number; retries: number; last_error: string | null; next_try_in_s: number | null; sleep_s?: number | null; last_success_ago_s: number | null }
export interface Stage { retry?: StageHealth | null; waiting?: string | null; running?: { clip: string; pid: number }[]; name: string; done: number; total: number; seconds_per_clip: number | null; eta_s: number | null; note: string }
export type ProjectState = 'new' | 'processing' | 'needs_input' | 'complete'
export interface Progress {
  state: ProjectState; folder: string; project: string; clips?: number; footage_gb?: number; percent?: number; eta_s?: number
  stages?: Stage[]; needs?: string[]; running?: boolean; job_running: boolean; has_gps?: boolean; workers?: number; max_workers?: number; can_add_worker?: boolean; add_worker_reason?: string; runnable?: number; worker_list?: { pid: number; clip: string | null; stage: string | null }[]; active?: { clip: string; stage: string }[]
}
export interface Coverage { clips: number; stages: string[]; totals: Record<string, number>; blocked: Record<string, string[]>; missing: { clip: string; stage: string; state: string }[]; complete: boolean }
export type ItemStatus = 'ok' | 'failed' | 'active' | 'stale' | null
export interface StateMatrix { stages: string[]; clips: Record<string, Record<string, ItemStatus>>; dependents: Record<string, string[]> }

export interface TrackOverview {
  present: boolean; error?: string; file?: string; samples?: number; start_utc?: string; end_utc?: string; duration_h?: number; moving_h?: number; distance_km?: number | null
  ascent_m?: number; descent_m?: number; avg_speed_kmh?: number | null; avg_pace_min_km?: number | null; max_altitude_m?: number | null; min_altitude_m?: number | null
  avg_hr?: number | null; max_hr?: number | null; gaps_over_10s?: number; bbox?: [number, number, number, number]; line?: [number, number][]
}
export interface Results { starters: number | null; finishers: number | null; finished: boolean | null; position: number | null }
export interface Meta {
  timezone?: string; title: string | null; date: string | null; distance_km?: number | null; results: Results
  defaults: { title: string | null; date: string | null; earliest_capture_utc: string | null }; effective: { title: string | null; date: string | null }
}
export interface ScriptItem { type: 'vo' | 'clip' | 'broll'; clip: string; text?: string; basis?: string[]; why?: string; seconds?: number; from?: string; to?: string; lines?: string[]; refs?: { clip: string; si: number; w0: number; w1: number }[] }
export interface ScriptDraft {
  title: string | null; story: string | null; items: ScriptItem[]; skipped: { clip: string; why: string }[]; report: { total_s?: number; target_s?: number; vo_s?: number; clip_s?: number; broll_s?: number; vo_words?: number; clips_used?: number; clips_skipped?: number }
  problems: string[]; warnings: string[]; created: string; target_s: number; target_source?: string; wpm: number; model: string; revised: boolean; draft_of?: string | null
}
export interface Script2State { draft: ScriptDraft | null; drafts: string[]; pins: ScriptPins; running: boolean; last_exit: number | null; log: string[]; used: string[]; key_configured: boolean }
export interface WordEdit { orig: string; src: 'user' | 'gemini'; why?: string | null; user_text?: string | null; gemini_text?: string | null }
export type WordMark = 'must' | 'never'
export interface WordT { i?: number; w: string; t0: number; t1: number; p?: number | null; e?: WordEdit; m?: WordMark }
export interface Seg { si: number; part?: number; play0?: number; play1?: number; words: WordT[]; clip: string; t0: number; t1: number; lang: string; text: string; text_en: string | null; flagged: boolean; who: 'wearer' | 'other' | null }
export interface ScriptLine { says?: string[]; seg: number; film_start_s: number; seconds: number; clip: string; text: string; words: number; est_speak_s: number; budget_words: number }
export interface ScriptDoc { file: string; title: string | null; provider?: string; model?: string; target_s: number; wpm: number; style?: string; lines: ScriptLine[]; total_words: number; total_speak_s: number; remaining_problems: { seg: number; problem: string }[]; seconds_llm?: number }
export interface ScriptState { key_configured: boolean; providers: Record<string, { models: string[]; default: string; configured: boolean }>; models: string[]; llm: { provider: string; model: string }; running: boolean; last_exit: number | null; log: string; latest: ScriptDoc | null; scripts: number }
export interface PlanOption { tech: string; score: number }
export interface PlanSegment {
  id: string; index: number; clip: string; cand_id: string; film_start_s: number; beats: number; dur_s: number; clip_start_s: number; utc_start: string; utc_end: string
  technique: string; family: string; hero: boolean; forced: boolean; speech: boolean; locked: boolean; options: PlanOption[]
  sound?: { gain_db: number; why: string[] }; kind?: string; view?: string; transition?: { type: 'cut' | 'dissolve' | 'dip' | 'whip'; beats: number; dur_s: number; why: string }
}
export interface EditState {
  settings: { length_s: number; bpm: number; bar_beats: number; seed: number; wpm: number; style: string }
  overrides: { locked: { wid: string }[]; tech_force: Record<string, string>; bans_cands: string[]; bans_techs: string[]; clip_weight: Record<string, number>; transitions?: Record<string, string> }
  plan: null | { generated_at: string; film: { length_s: number; beats: number; bpm: number }; segments: PlanSegment[]; clips_in_plan: number; missing_clips: string[]; orphaned_overrides: string[]; technique_seconds: Record<string, number>; warnings: string[] }
}
export interface VoiceLine { seg: number; text: string; source: 'synth' | 'recorded'; has_recording: boolean; film_start_s: number; window_s: number; room_s: number; natural_s: number; played_s: number; overrun_s: number; tempo: number; fit: 'ok' | 'sped' | 'over'; synth_s: number }
export interface VoiceoverState { engines: { id: string; label: string; voices: { name: string; lang: string }[] }[]; state: { engine: string | null; voice: string | null; rate: number; use: Record<string, string> }; timings: { script: string; engine: string; voice: string; rate: number; film_length_s: number; lines: VoiceLine[]; measured_wpm: number | null; over: number[]; sped: number[] } | null; script: string | null; cached?: { engine: string; voice: string; rate: number; key: string; measured_wpm: number | null; over: number; sped: number; active: boolean }[]; lines: number; building: boolean; progress?: { state?: string; done?: number; total?: number }; error?: string | null }
export interface FilmState { state: 'noplan' | 'none' | 'starting' | 'audio' | 'rendering' | 'done' | 'error'; running: boolean; key?: string; frames_done?: number; frames_total?: number; placeholders?: string[]; error?: string | null; length_s?: number }
export interface FinalState { state: 'noplan' | 'none' | 'starting' | 'rendering' | 'assembling' | 'done' | 'error' | 'stopped' | 'partial'; running: boolean; settings: { size: string; fps: number; bitrate: string }; frames_done?: number; frames_total?: number; pieces_done?: number; pieces_total?: number; started?: number; error?: string | null; has_file?: boolean }
export interface MusicAnalysis { bpm: number; offset_s: number; bar_beats?: number; duration_s: number; usable_beats: number; sections: [number, number, number][]; confidence: number }
export interface MusicState { file: string | null; name?: string | null; analysis: MusicAnalysis | null; waveform?: number[] | null; spectrogram?: boolean }
export interface ClockState { offset_s: number; verified: boolean; note: string | null; drift_s_per_day?: number | null; anchors: unknown[]; has_track: boolean }
export interface WhoState { ready: boolean; reason?: string; profile: boolean; sheet?: boolean; clusters?: { cluster: number; n: number; clips: number; rear_fraction: number; median_size_px: number }[]; suggested?: { clusters: number[]; confident: boolean; why: string } }
export interface EditResponse { edit: EditState; techniques: { id: string; family: string; hero: boolean; dur: number[]; dialogue_ok: boolean }[]; script: Record<string, { text: string; says: string[]; words: number | null; budget: number | null }> }
export interface ClipInfo { audio_original?: boolean; audio_clean?: boolean; id: string; start_utc: string; duration_s: number; has_note: boolean; thumb: 'best' | 'quick' | null; thumb_overlay?: boolean; steady: number | null; candidates: number | null }
export interface Near { name: string; kind: string; distance_m: number }
export interface PlacePoint { label: string; lat: number; lon: number; address: { display_name?: string; road?: string; county?: string; country?: string } | null; nearby: Near[] | null }
export interface Places { covered: boolean; note?: string; points: PlacePoint[]; summary?: { places: string[]; road?: string; county?: string; country?: string; text: string } }
export interface Line { si: number; part?: number; play0?: number; play1?: number; words: WordT[]; t0: number; t1: number; lang: string; text: string; text_en: string | null; flagged: boolean; who: 'wearer' | 'other' | null }
export interface Why { starts_because: string; ends_because?: string; steadiness: number; shake_dps: number; exposure_ok: number; scenic: number; lens_blocked: number; score: number; speech: boolean; chatter: number }
export interface Candidate { id: string; kind?: 'span' | 'best' | 'speech' | 'person' | 'you' | 'scene'; view?: string; priority?: number; span?: number; start_s: number; end_s: number; start_utc: string; quality: number; energy: number; features: Record<string, number>; settings: string[]; people: number; why?: Why }
export interface Unusable { start_s: number; end_s: number; usable: false; reasons: string[]; detail: string | null; starts_because: string; ends_because?: string; stats: Record<string, number | string | null> }
export interface Sounds { seconds: Record<string, number>; windows: { t0: number; t1: number; cats: Record<string, number>; top: [string, number][] }[]; hints: Record<string, [string, number]> }
export interface ClipDetail {
  sounds?: Sounds
  audio_files?: { original: boolean; clean: boolean }
  id: string; note: string; time: Record<string, string | number | boolean | null>; video: Record<string, any>; camera?: Record<string, string>
  motion: Record<string, number | null> | null; audio: { summary: any; segments: { label: string; t0_s: number; t1_s: number }[] } | null
  transcript: Line[]; scenes: { summary: any; items: any[] } | null; identity: Record<string, number> | null; candidates: Candidate[] | null; person?: { t: number; yaw: number; pitch: number; who: 'you' | 'other'; speaking: boolean; person?: number }[] | null; clarity?: { t: number; yaw: number; pitch: number; score?: number }[] | null; focus?: { t: number; yaw: number; pitch: number; who: 'you' | 'other'; speaking: boolean }[] | null; preview?: boolean; heading?: { t: number[]; deg: number[] } | null; unusable?: Unusable[] | null; thresholds?: { usable_score: number; min_len_s: number; max_stretch_s: number } | null
  places?: Places | null; exposure: Record<string, any> | null; thumb: { kind: string; t_s: number; why: string; overlay?: boolean } | null; track?: Record<string, any>; track_text?: string
}
export interface Notes { folder: string; clips: Record<string, string>; updated: Record<string, string>; vo_must?: { folder: string; folder_ordered: boolean; clips: Record<string, string> } }
export interface VoPin { id: string; text: string; mode: 'clip' | 'ordered' | 'anywhere'; clip?: string }
export interface ScriptPins { include?: string[]; exclude?: string[]; vo?: VoPin[]; vo_never?: string[] }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j.detail || j.error || `HTTP ${r.status}`)
  return j as T
}
const q = (o: Record<string, string>) => new URLSearchParams(o).toString()

export const api = {
  last: () => call<{ folder: string | null }>('/api/last'),
  roots: () => call<{ roots: string[] }>('/api/roots'),
  browse: (path?: string) => call<Browse>('/api/browse' + (path ? '?' + q({ path }) : '')),
  progress: (folder: string) => call<Progress>('/api/progress?' + q({ folder })),
  coverage: (folder: string) => call<Coverage>('/api/coverage?' + q({ folder })),
  log: (folder: string) => call<{ lines: string[] }>('/api/log?' + q({ folder })),
  track: (folder: string) => call<TrackOverview>('/api/track?' + q({ folder })),
  uploadTrack: async (folder: string, file: File) => {
    const r = await fetch('/api/track?' + q({ folder, filename: file.name }), { method: 'POST', body: file })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`)
    return j as TrackOverview
  },
  clip: (folder: string, clip: string) => call<ClipDetail>('/api/clip?' + q({ folder, clip })),
  previewUrl: (folder: string, clip: string) => '/api/preview?' + q({ folder, clip }),
  thumbUrl: (folder: string, clip: string, v: string, overlay = false) => '/api/thumb?' + q({ folder, clip, v, ...(overlay ? { overlay: '1' } : {}) }),     // v: busts the browser cache when the picture changes
  meta: (folder: string) => call<Meta>('/api/meta?' + q({ folder })),
  saveMeta: (folder: string, patch: Partial<Pick<Meta, 'title' | 'date' | 'distance_km'>> & { results?: Partial<Results> }) => call<Meta>('/api/meta', { folder, ...patch }),
  transcript: (folder: string) => call<{ segments: Seg[] }>('/api/transcript?' + q({ folder })),
  script: (folder: string) => call<ScriptState>('/api/script?' + q({ folder })),
  setKey: (key: string, provider = 'vertex') => call<{ configured: boolean }>('/api/llm/key', { key, provider }),
  generateScript: (folder: string, o: { length: number; wpm?: number; style?: string; model?: string; provider?: string }) => call<{ started: boolean }>('/api/script/generate', { folder, ...o }),
  voiceover: (folder: string) => call<VoiceoverState>('/api/voiceover?' + q({ folder })),
  buildVoiceover: (folder: string, o: { engine?: string; voice?: string; rate?: number } = {}) => call<{ started: boolean }>('/api/voiceover/build', { folder, ...o }),
  markWords: (folder: string, clip: string, spans: { seg: number; from: number; to: number }[], state: 'must' | 'never' | 'none') => call<{ ok: boolean; marked: number }>('/api/transcript/mark', { folder, clip, spans, state }),
  script2: (folder: string, name = '') => call<Script2State>('/api/script2?' + q(name ? { folder, name } : { folder })),
  generateScript2: (folder: string, o: { revise?: boolean; target_s?: number; auto?: boolean } = {}) => call<{ started: boolean; reason?: string }>('/api/script2/generate', { folder, ...o }),
  editWord: (folder: string, clip: string, seg: number, word: number, text: string | null) => call<{ ok: boolean }>('/api/transcript/edit', text === null ? { folder, clip, seg, word, action: 'clear' } : { folder, clip, seg, word, text }),
  suggestTranscript: (folder: string) => call<{ started: boolean }>('/api/transcript/suggest', { folder }),
  transcriptFix: (folder: string) => call<{ usage?: { calls: number; input: number; output: number; paid_calls: number; cost_usd: number }; health?: StageHealth | null; calls_made?: number; calls_reused?: number; tokens?: { input: number; output: number }; state: string; done?: number; total?: number; fixes?: number; error?: string }>('/api/transcript/suggest?' + q({ folder })),
  clipAudioUrl: (folder: string, clip: string, kind: 'original' | 'clean') => '/api/clip/audio?' + q({ folder, clip, kind }),
  editScript: (folder: string, texts: Record<string, string>) => call<{ saved: string | null; speaking: boolean }>('/api/script/edit', { folder, texts }),
  voiceoverUse: (folder: string, seg: number, use: 'synth' | 'recorded') => call<{ ok: boolean }>('/api/voiceover/use', { folder, seg, use }),
  voiceoverAudio: (folder: string, seg?: number, source?: string, track?: string) => '/api/voiceover/audio?' + q(seg === undefined ? (track ? { folder, track } : { folder }) : { folder, seg: String(seg), source: source ?? 'synth' }),
  async recordVoiceover(folder: string, seg: number, file: Blob) {
    const r = await fetch('/api/voiceover/record?' + q({ folder, seg: String(seg) }), { method: 'POST', body: file }); const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`)
  },
  deleteRecording: (folder: string, seg: number) => fetch('/api/voiceover/record?' + q({ folder, seg: String(seg) }), { method: 'DELETE' }),
  film: (folder: string) => call<FilmState>('/api/film?' + q({ folder })),
  startFilm: (folder: string, force = false) => call<{ started: boolean }>('/api/film/start', { folder, force }),
  stopFilm: (folder: string) => call<{ ok: boolean }>('/api/film/stop', { folder }),
  filmUrl: (folder: string) => '/api/film/index.m3u8?' + q({ folder }),
  final: (folder: string) => call<FinalState>('/api/final?' + q({ folder })),
  startFinal: (folder: string, o: { size?: string; fps?: number } = {}) => call<{ started: boolean }>('/api/final/start', { folder, ...o }),
  stopFinal: (folder: string) => call<{ ok: boolean }>('/api/final/stop', { folder }),
  finalUrl: (folder: string) => '/api/final/file?' + q({ folder }),
  music: (folder: string) => call<MusicState>('/api/music?' + q({ folder })),
  async uploadMusic(folder: string, file: File) {
    const r = await fetch('/api/music?' + q({ folder, filename: file.name }), { method: 'POST', body: file }); const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`)
    return j as MusicState & { warning?: string }
  },
  musicAudioUrl: (folder: string) => '/api/music/audio?' + q({ folder }),
  musicSpectrogramUrl: (folder: string, v: string) => '/api/music/spectrogram?' + q({ folder, v }),
  removeMusic: (folder: string) => fetch('/api/music?' + q({ folder }), { method: 'DELETE' }),
  clock: (folder: string) => call<ClockState>('/api/clock?' + q({ folder })),
  clockSuggest: (folder: string) => call<{ current: number; suggestions: { offset_s: number; votes: number; confidence: number; score: number; clips?: string[] }[] }>('/api/clock/suggest?' + q({ folder })),
  setClock: (folder: string, offset_seconds: number) => call<{ clock: ClockState; retimed: number }>('/api/clock', { folder, offset_seconds }),
  who: (folder: string, refresh = false) => call<WhoState>('/api/who?' + q({ folder, refresh: refresh ? 'true' : 'false' })),
  whoSheetUrl: (folder: string, v: number) => '/api/who/sheet?' + q({ folder, v: String(v) }),
  whoMeUrl: (folder: string, v: number) => '/api/who/me?' + q({ folder, v: String(v) }),
  setWho: (folder: string, me: number[]) => call<{ ok: boolean }>('/api/who', { folder, me }),
  editGet: (folder: string) => call<EditResponse>('/api/edit?' + q({ folder })),
  propose: (folder: string, o: { length_s?: number; bpm?: number; seed?: number; keep?: boolean }) => call<{ edit: EditState }>('/api/edit/propose', { folder, ...o }),
  override: (folder: string, body: Record<string, unknown>) => call<{ edit: EditState }>('/api/edit/override', { folder, ...body }),
  clips: (folder: string) => call<{ clips: ClipInfo[] }>('/api/clips?' + q({ folder })),
  notes: (folder: string) => call<Notes>('/api/notes?' + q({ folder })),
  saveNote: (folder: string, text: string, clip?: string) => call<Notes>('/api/notes', { folder, text, clip }),
  saveVo: (folder: string, text: string, clip?: string, ordered?: boolean) => call<Notes>('/api/notes', { folder, kind: 'vo', text, clip, ordered }),
  saveScriptPins: (folder: string, pins: ScriptPins) => call<ScriptPins>('/api/script2/pins', { folder, ...pins }),
  open: (folder: string, extra: { languages?: string; gps?: string } = {}) => call<{ started: boolean }>('/api/open', { folder, ...extra }),
  run: (folder: string) => call<{ started: boolean }>('/api/run', { folder }),
  state: (folder: string) => call<StateMatrix>('/api/state?' + q({ folder })),
  clear: (folder: string, items: { clip: string; stage: string }[]) => call<{ cleared: number }>('/api/clear', { folder, items }),
  stop: (folder: string, pid?: number) => call<{ stopped: number }>('/api/stop', { folder, pid }),
}
