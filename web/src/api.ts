// Typed client for the FastAPI server (src/strata360/server/app.py). Same-origin; the token (if any) travels as a cookie.
export interface BrowseEntry { name: string; path: string; kind: 'dir'; is_project: boolean }
export interface Browse { path: string; parent: string | null; footage_here: number; is_project: boolean; entries: BrowseEntry[] }
export interface Stage { name: string; done: number; total: number; seconds_per_clip: number | null; eta_s: number | null; note: string }
export type ProjectState = 'new' | 'processing' | 'needs_input' | 'complete'
export interface Progress {
  state: ProjectState; folder: string; project: string; clips?: number; footage_gb?: number; percent?: number; eta_s?: number
  stages?: Stage[]; needs?: string[]; running?: boolean; job_running: boolean; has_gps?: boolean
}

export interface TrackOverview {
  present: boolean; error?: string; file?: string; samples?: number; start_utc?: string; end_utc?: string; duration_h?: number; moving_h?: number; distance_km?: number | null
  ascent_m?: number; descent_m?: number; avg_speed_kmh?: number | null; avg_pace_min_km?: number | null; max_altitude_m?: number | null; min_altitude_m?: number | null
  avg_hr?: number | null; max_hr?: number | null; gaps_over_10s?: number; bbox?: [number, number, number, number]; line?: [number, number][]
}
export interface ClipInfo { id: string; start_utc: string; duration_s: number; has_note: boolean }
export interface Notes { folder: string; clips: Record<string, string>; updated: Record<string, string> }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j.detail || j.error || `HTTP ${r.status}`)
  return j as T
}
const q = (o: Record<string, string>) => new URLSearchParams(o).toString()

export const api = {
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
  clips: (folder: string) => call<{ clips: ClipInfo[] }>('/api/clips?' + q({ folder })),
  notes: (folder: string) => call<Notes>('/api/notes?' + q({ folder })),
  saveNote: (folder: string, text: string, clip?: string) => call<Notes>('/api/notes', { folder, text, clip }),
  open: (folder: string, extra: { languages?: string; gps?: string } = {}) => call<{ started: boolean }>('/api/open', { folder, ...extra }),
  run: (folder: string) => call<{ started: boolean }>('/api/run', { folder }),
  stop: (folder: string) => call<{ stopped: boolean }>('/api/stop', { folder }),
}
