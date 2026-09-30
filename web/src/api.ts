// Typed client for the FastAPI server (src/strata360/server/app.py). Same-origin; the token (if any) travels as a cookie.
export interface BrowseEntry { name: string; path: string; kind: 'dir'; is_project: boolean }
export interface Browse { path: string; parent: string | null; footage_here: number; is_project: boolean; can_create: boolean; entries: BrowseEntry[] }
export interface Stage { waiting?: string | null; running?: { clip: string; pid: number }[]; name: string; done: number; total: number; seconds_per_clip: number | null; eta_s: number | null; note: string }
export type ProjectState = 'new' | 'processing' | 'needs_input' | 'complete'
export interface Progress {
  state: ProjectState; folder: string; project: string; clips?: number; footage_gb?: number; percent?: number; eta_s?: number
  stages?: Stage[]; needs?: string[]; running?: boolean; job_running: boolean; has_gps?: boolean; workers?: number; max_workers?: number; runnable?: number; worker_list?: { pid: number; clip: string | null; stage: string | null }[]; active?: { clip: string; stage: string }[]
}
export type ItemStatus = 'ok' | 'failed' | 'active' | 'stale' | null
export interface StateMatrix { stages: string[]; clips: Record<string, Record<string, ItemStatus>>; dependents: Record<string, string[]> }

export interface TrackOverview {
  present: boolean; error?: string; file?: string; samples?: number; start_utc?: string; end_utc?: string; duration_h?: number; moving_h?: number; distance_km?: number | null
  ascent_m?: number; descent_m?: number; avg_speed_kmh?: number | null; avg_pace_min_km?: number | null; max_altitude_m?: number | null; min_altitude_m?: number | null
  avg_hr?: number | null; max_hr?: number | null; gaps_over_10s?: number; bbox?: [number, number, number, number]; line?: [number, number][]
}
export interface Results { starters: number | null; finishers: number | null; finished: boolean | null; position: number | null }
export interface Meta {
  timezone?: string; title: string | null; date: string | null; results: Results
  defaults: { title: string | null; date: string | null; earliest_capture_utc: string | null }; effective: { title: string | null; date: string | null }
}
export interface Seg { clip: string; t0: number; t1: number; lang: string; text: string; text_en: string | null; flagged: boolean; who: 'wearer' | 'other' | null }
export interface ClipInfo { id: string; start_utc: string; duration_s: number; has_note: boolean; thumb: 'best' | 'quick' | null; steady: number | null; candidates: number | null }
export interface Near { name: string; kind: string; distance_m: number }
export interface PlacePoint { label: string; lat: number; lon: number; address: { display_name?: string; road?: string; county?: string; country?: string } | null; nearby: Near[] | null }
export interface Places { covered: boolean; note?: string; points: PlacePoint[]; summary?: { places: string[]; road?: string; county?: string; country?: string; text: string } }
export interface Line { t0: number; t1: number; lang: string; text: string; text_en: string | null; flagged: boolean; who: 'wearer' | 'other' | null }
export interface Candidate { id: string; start_s: number; end_s: number; start_utc: string; quality: number; energy: number; features: Record<string, number>; settings: string[]; people: number }
export interface ClipDetail {
  id: string; note: string; time: Record<string, string | number | boolean | null>; video: Record<string, any>; camera?: Record<string, string>
  motion: Record<string, number | null> | null; audio: { summary: any; segments: { label: string; t0_s: number; t1_s: number }[] } | null
  transcript: Line[]; scenes: { summary: any; items: any[] } | null; identity: Record<string, number> | null; candidates: Candidate[] | null
  places?: Places | null; exposure: Record<string, any> | null; thumb: { kind: string; t_s: number; why: string } | null; track?: Record<string, any>; track_text?: string
}
export interface Notes { folder: string; clips: Record<string, string>; updated: Record<string, string> }

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
  log: (folder: string) => call<{ lines: string[] }>('/api/log?' + q({ folder })),
  track: (folder: string) => call<TrackOverview>('/api/track?' + q({ folder })),
  uploadTrack: async (folder: string, file: File) => {
    const r = await fetch('/api/track?' + q({ folder, filename: file.name }), { method: 'POST', body: file })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`)
    return j as TrackOverview
  },
  clip: (folder: string, clip: string) => call<ClipDetail>('/api/clip?' + q({ folder, clip })),
  thumbUrl: (folder: string, clip: string, v: string) => '/api/thumb?' + q({ folder, clip, v }),
  meta: (folder: string) => call<Meta>('/api/meta?' + q({ folder })),
  saveMeta: (folder: string, patch: Partial<Pick<Meta, 'title' | 'date'>> & { results?: Partial<Results> }) => call<Meta>('/api/meta', { folder, ...patch }),
  transcript: (folder: string) => call<{ segments: Seg[] }>('/api/transcript?' + q({ folder })),
  clips: (folder: string) => call<{ clips: ClipInfo[] }>('/api/clips?' + q({ folder })),
  notes: (folder: string) => call<Notes>('/api/notes?' + q({ folder })),
  saveNote: (folder: string, text: string, clip?: string) => call<Notes>('/api/notes', { folder, text, clip }),
  open: (folder: string, extra: { languages?: string; gps?: string } = {}) => call<{ started: boolean }>('/api/open', { folder, ...extra }),
  run: (folder: string) => call<{ started: boolean }>('/api/run', { folder }),
  state: (folder: string) => call<StateMatrix>('/api/state?' + q({ folder })),
  clear: (folder: string, items: { clip: string; stage: string }[]) => call<{ cleared: number }>('/api/clear', { folder, items }),
  stop: (folder: string, pid?: number) => call<{ stopped: number }>('/api/stop', { folder, pid }),
}
