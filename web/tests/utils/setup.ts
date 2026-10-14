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

// leaflet-node (loaded by the files that draw a map) reads an image's `src` as a file path, so every `/api/...` picture (map tiles, thumbnails) logged "Could not find image". The app's own URL stays in the attribute (tests read it); what is loaded is a 1 px picture.
// (Done once the test file has imported what it needs, so a file that never loads leaflet-node is not touched by it.)
const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
beforeAll(() => {
  const proto = globalThis.HTMLImageElement?.prototype, d = proto && Object.getOwnPropertyDescriptor(proto, 'src')
  if (!proto || !d?.set || (d.set as { pixel?: boolean }).pixel) return
  const set = function (this: HTMLImageElement, value: string) {
    if (typeof value === 'string' && value.startsWith('/')) { d.set!.call(this, PIXEL); this.setAttribute('src', value) } else d.set!.call(this, value)
  }
  ;(set as { pixel?: boolean }).pixel = true
  Object.defineProperty(proto, 'src', { ...d, set })
})
