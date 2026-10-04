import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent } from '@testing-library/react'
import { setup, waitFor } from '../utils/render'
import PanoPlayer from '../../src/components/PanoPlayer'
import { stubBrowserApis, stubMedia } from '../utils/media'
import type { AimPath } from '../../src/api'

// (Its own file: a test that imports Leaflet gets a canvas of its own from leaflet-node, which these stand-ins for WebGL and 2D drawing would not replace.)
const rel: AimPath = { kind: 'rel', t: [0, 1, 2], yaw: [0, 0, 0], pitch: [0, 0, 0], fov: [40, 40, 40], on: [true, true, true] }

describe('PanoPlayer: the aim of a point camera over the look-around', () => {
  const arcs: number[] = []
  const gl = new Proxy({} as Record<string, unknown>, { get: (t, k) => (k in t ? t[k as string] : (..._a: unknown[]) => ({})) })
  const ctx2d = new Proxy({} as Record<string, unknown>, { get: (t, k) => (k === 'arc' ? (x: number) => { arcs.push(x) } : k in t ? t[k as string] : () => {}), set: () => true })
  beforeEach(() => {
    arcs.length = 0; stubMedia(); stubBrowserApis(); vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((type: string) => (type === 'webgl2' ? gl : ctx2d)) as never)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 640 }); Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 360 }); HTMLElement.prototype.setPointerCapture = vi.fn()
  })
  afterEach(() => { vi.restoreAllMocks(); delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth; delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight })

  it('draws the dot where the camera aims in the picture and moves it as you look around', async () => {
    setup(<PanoPlayer src="/v.mp4" label="M1" aimPath={rel} />)
    await waitFor(() => expect(arcs.length).toBeGreaterThan(1)); const first = arcs.at(-1)!; expect(first).toBeCloseTo(320, 0)                       // (looking along the road, at the middle: the camera aims dead ahead)
    const canvas = document.querySelector('canvas:not([data-aim-overlay])') as HTMLCanvasElement; fireEvent.pointerDown(canvas, { clientX: 300, clientY: 100, pointerId: 1 }); fireEvent.pointerMove(canvas, { clientX: 200, clientY: 100, pointerId: 1 })
    await waitFor(() => expect(arcs.at(-1)!).toBeLessThan(first - 20)); fireEvent.pointerUp(canvas, { pointerId: 1 })
  })

  it('draws nothing without a camera', async () => { setup(<PanoPlayer src="/v.mp4" label="M1" />); await new Promise(r => setTimeout(r, 100)); expect(arcs).toEqual([]) })
})

