import { http, HttpResponse } from 'msw'
import { makeBrowse, makeNotes, makeProgress, makeStateMatrix } from './factories'

// Default happy-path handlers, one per endpoint. Only the endpoints the tests so far need are here: when a test hits an endpoint that is missing,
// msw fails it loudly (onUnhandledFrame: 'error'), so add the handler here (with a factory in factories.ts) rather than inline in the test.
// Per-test variations belong in the test, via `mockGet`/`mockPost`/`mockError` from ./api.
export const handlers = [
  http.get('/api/last', () => HttpResponse.json({ folder: null })),
  http.get('/api/browse', () => HttpResponse.json(makeBrowse())),
  http.get('/api/notes', () => HttpResponse.json(makeNotes())),
  http.post('/api/notes', async ({ request }) => HttpResponse.json(makeNotes({ folder: ((await request.json()) as { text: string }).text }))),
  http.post('/api/open', () => HttpResponse.json({ started: true })),
  http.get('/api/progress', () => HttpResponse.json(makeProgress())),
  http.get('/api/log', () => HttpResponse.json({ lines: [] })),
  http.get('/api/state', () => HttpResponse.json(makeStateMatrix())),
  http.post('/api/run', () => HttpResponse.json({ started: true })),
  http.post('/api/stop', () => HttpResponse.json({ stopped: 1 })),
  http.post('/api/clear', () => HttpResponse.json({ cleared: 1 })),
]
