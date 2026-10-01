import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { server } from './server'

// Unit project (node): node's fetch rejects relative URLs, so resolve `/api/...` against a fixed origin (installed after msw patches fetch).
// Tests that only stub fetch themselves are unaffected.
const origin = 'http://localhost:3000'
let patched: typeof fetch | undefined
beforeAll(() => {
  vi.stubGlobal('location', new URL(origin + '/')) // msw resolves the relative handler paths against `location`
  server.listen({ onUnhandledFrame: 'error' })
  patched = globalThis.fetch
  globalThis.fetch = ((input, init) => patched!(typeof input === 'string' && input.startsWith('/') ? origin + input : input, init)) as typeof fetch
})
afterEach(() => { server.resetHandlers() })
afterAll(() => { vi.unstubAllGlobals(); globalThis.fetch = patched!; server.close() })
