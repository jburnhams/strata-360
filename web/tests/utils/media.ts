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

/** jsdom has no layout: every element's getBoundingClientRect is all zeros. Give them a size (for code that turns a mouse position into a position in an element). Returns a function that undoes it.
 *  (Leaflet components do not need this: the tests run them on `leaflet-node`, which supplies layout and a canvas; see vitest.config.ts.) */
export function stubRect(width = 800, height = 420) {
  const r = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: width, bottom: height, width, height, toJSON() {} } as DOMRect)
  return () => r.mockRestore()
}
