import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import { cleanup } from '@testing-library/react'
import * as axeMatchers from 'vitest-axe/matchers'
import '@testing-library/jest-dom/vitest'
import { server } from './server'

expect.extend(axeMatchers)

// jsdom (integration project): relative `/api/...` URLs resolve against jsdom's origin, so msw sees them as they are.
// An endpoint without a handler fails the test (see handlers.ts) instead of silently hitting the network.
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => { server.resetHandlers(); cleanup() })
afterAll(() => server.close())

// Node 25+ defines its own `localStorage` global, which is undefined without --localstorage-file and hides jsdom's: put a working in-memory one back so storage behaves as in a browser.
if (typeof globalThis.localStorage?.getItem !== 'function') {
  const data = new Map<string, string>()
  const storage: Storage = {
    get length() { return data.size },
    clear: () => data.clear(),
    getItem: k => data.get(k) ?? null,
    key: i => Array.from(data.keys())[i] ?? null,
    removeItem: k => { data.delete(k) },
    setItem: (k, v) => { data.set(k, String(v)) },
  }
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true, writable: true })
}
