import { delay, http, HttpResponse, type JsonBodyType } from 'msw'
import { server } from './server'

type Body = JsonBodyType | ((req: Request) => JsonBodyType | Promise<JsonBodyType>)
const resolve = (body: Body) => async ({ request }: { request: Request }) => {
  try {
    const res = typeof body === 'function' ? await body(request) : body
    return HttpResponse.json(res ? JSON.parse(JSON.stringify(res)) : res)
  } catch (e) {
    console.error('RESOLVE CRASHED', e)
    throw e
  }
}

export const mockGet = (path: string, body: Body) => server.use(http.get(path, resolve(body)))
export const mockPost = (path: string, body: Body) => server.use(http.post(path, resolve(body)))
export const mockError = (path: string, status: number, detail?: string, method: 'get' | 'post' = 'get') =>
  server.use(http[method](path, () => HttpResponse.json(detail === undefined ? {} : { detail }, { status })))
export const mockNetworkError = (path: string, method: 'get' | 'post' = 'get') => server.use(http[method](path, () => HttpResponse.error()))

export interface Seen { url: URL; method: string; body: unknown }
export function recordRequests(path: string): Seen[] {
  const seen: Seen[] = []
  server.events.on('request:start', async ({ request }) => {
    const url = new URL(request.url)
    if (url.pathname !== path) return
    const text = await request.clone().text()
    let body: unknown = text || undefined
    try { body = text ? JSON.parse(text) : undefined } catch { }
    seen.push({ url, method: request.method, body })
  })
  return seen
}

export const mockPending = (path: string, method: 'get' | 'post' = 'get') => server.use(http[method](path, async () => { await delay('infinite') }))
