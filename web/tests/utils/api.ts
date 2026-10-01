import { delay, http, HttpResponse, type JsonBodyType } from 'msw'
import { server } from './server'

// Per-test backend overrides on top of the default handlers. Paths are the same-origin `/api/...` paths the client calls (no query string).
type Body = JsonBodyType | ((req: Request) => JsonBodyType | Promise<JsonBodyType>)
const resolve = (body: Body) => async ({ request }: { request: Request }) => HttpResponse.json(typeof body === 'function' ? await body(request) : body)

export const mockGet = (path: string, body: Body) => server.use(http.get(path, resolve(body)))
export const mockPost = (path: string, body: Body) => server.use(http.post(path, resolve(body)))
/** A JSON error the way FastAPI sends it: `{ detail }` with the given status. */
export const mockError = (path: string, status: number, detail?: string, method: 'get' | 'post' = 'get') =>
  server.use(http[method](path, () => HttpResponse.json(detail === undefined ? {} : { detail }, { status })))
/** A dropped connection (fetch rejects). */
export const mockNetworkError = (path: string, method: 'get' | 'post' = 'get') => server.use(http[method](path, () => HttpResponse.error()))

export interface Seen { url: URL; method: string; body: unknown }
/**
 * Watch the requests a path receives (any method) without changing its response: `const seen = recordRequests('/api/notes')`, then `seen.at(-1)?.body`.
 * Bodies are parsed as JSON when they are JSON, otherwise left as text.
 */
export function recordRequests(path: string): Seen[] {
  const seen: Seen[] = []
  server.events.on('request:start', async ({ request }) => {
    const url = new URL(request.url)
    if (url.pathname !== path) return
    const text = await request.clone().text()
    let body: unknown = text || undefined
    try { body = text ? JSON.parse(text) : undefined } catch { /* not JSON */ }
    seen.push({ url, method: request.method, body })
  })
  return seen
}

/** A request that never answers, to look at the loading state. */
export const mockPending = (path: string, method: 'get' | 'post' = 'get') => server.use(http[method](path, async () => { await delay('infinite') }))
