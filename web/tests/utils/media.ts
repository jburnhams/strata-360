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

/** Leaflet measures its container: jsdom has no layout, so give every element a size. Returns a function that undoes it. */
export function stubLayout(width = 800, height = 420) {
  const d = (k: string, v: number) => Object.defineProperty(HTMLElement.prototype, k, { configurable: true, get: () => v })
  d('clientWidth', width); d('clientHeight', height); d('offsetWidth', width); d('offsetHeight', height)
  const ctx = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)                      // no canvas in jsdom: Leaflet then draws SVG
  const r = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: width, bottom: height, width, height, toJSON() {} } as DOMRect)
  return () => { r.mockRestore(); ctx.mockRestore(); for (const k of ['clientWidth', 'clientHeight', 'offsetWidth', 'offsetHeight']) delete (HTMLElement.prototype as unknown as Record<string, unknown>)[k] }
}
