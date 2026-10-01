import { vi } from 'vitest'

/** jsdom has no media playback: stub the HTMLMediaElement methods players call (call in a `beforeEach`). Returns the spies. */
export function stubMedia() {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  const load = vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  return { play, pause, load }
}

/** jsdom lacks these browser APIs; components that use them need a no-op version. */
export function stubBrowserApis() {
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } })
}
