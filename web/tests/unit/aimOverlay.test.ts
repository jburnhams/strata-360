import { describe, expect, it } from 'vitest'
import { aimAt, dir, drawAim, frameDirections, project, type View } from '../../src/aimOverlay'
import type { AimPath } from '../../src/api'

const view = (o: Partial<View> = {}): View => ({ yaw: 0, pitch: 0, fov: 90, aspect: 16 / 9, ...o })

describe('project: where a direction falls in a view', () => {
  it('puts what the view looks at in the middle, and the edge of the field of view at the edge of the picture', () => {
    const c = project(view(), dir(0, 0))!; expect(c.x).toBeCloseTo(0); expect(c.y).toBeCloseTo(0)
    expect(project(view(), dir(45, 0))!.x).toBeCloseTo(1); expect(project(view(), dir(-45, 0))!.x).toBeCloseTo(-1)
    const up = project(view(), dir(0, 10))!; expect(up.y).toBeGreaterThan(0); expect(project(view(), dir(0, -10))!.y).toBeLessThan(0)
    expect(project(view(), dir(0, (Math.atan(Math.tan(Math.PI / 4) / (16 / 9)) * 180) / Math.PI))!.y).toBeCloseTo(1, 2)          // the top edge: half the vertical field of view
  })
  it('follows the view when it is turned or tipped (dragging, or an aim that follows someone)', () => {
    const a = project(view({ yaw: 90 }), dir(90, 0))!; expect(a.x).toBeCloseTo(0); expect(project(view({ yaw: 90 }), dir(0, 0))).toBeNull()                  // (what was ahead is now exactly to the side: not in front of the viewer)
    const b = project(view({ yaw: 350 }), dir(10, 0))!; expect(b.x).toBeGreaterThan(0.2); const c = project(view({ pitch: 20 }), dir(0, 20))!; expect(c.y).toBeCloseTo(0)
  })
  it('says nothing for what is behind the viewer', () => { expect(project(view(), dir(180, 0))).toBeNull(); expect(project(view(), dir(100, 0))).toBeNull() })
})

describe('the outline of the camera frame', () => {
  it('is a closed loop round the frame', () => {
    const d = frameDirections({ yaw: 30, pitch: -5, fov: 60 }); expect(d).toHaveLength(49); for (let k = 0; k < 3; k++) expect(d[0][k]).toBeCloseTo(d[48][k])
  })
  it('fills the picture exactly when the viewer sees through the camera itself', () => {
    const aim = { yaw: 40, pitch: -8, fov: 70 }, pts = frameDirections(aim).map(x => project(view({ ...aim }), x)!)
    for (const p of pts) expect(Math.max(Math.abs(p.x), Math.abs(p.y))).toBeCloseTo(1, 5)
  })
  it('is smaller and inside the picture when the viewer is wider than the camera, and moves as the viewer pans', () => {
    const aim = { yaw: 0, pitch: 0, fov: 40 }, wide = frameDirections(aim).map(x => project(view({ fov: 100 }), x)!); expect(Math.max(...wide.map(p => Math.abs(p.x)))).toBeLessThan(0.5)
    const panned = frameDirections(aim).map(x => project(view({ fov: 100, yaw: 20 }), x)!); expect(Math.max(...panned.map(p => p.x))).toBeLessThan(Math.max(...wide.map(p => p.x)) - 0.2)
  })
})

describe('aimAt: the camera at a moment of the video', () => {
  const world: AimPath = { kind: 'world', t: [10, 11, 12], yaw: [170, -170, -150], pitch: [0, -2, -4], fov: [60, 70, 80], on: [true, true, true] }
  it('interpolates between samples, the short way round the compass', () => {
    const a = aimAt(world, 10.5)!; expect(((a.yaw + 360) % 360)).toBeCloseTo(180); expect(a.pitch).toBeCloseTo(-1); expect(a.fov).toBeCloseTo(65)
    expect(aimAt(world, 12)!.yaw).toBeCloseTo(-150)
  })
  it('is null outside the camera, before and after its stretch and where a sample is off', () => {
    expect(aimAt(world, 9.9)).toBeNull(); expect(aimAt(world, 12.1)).toBeNull(); expect(aimAt(null, 1)).toBeNull(); expect(aimAt({ ...world, t: [] }, 1)).toBeNull()
    expect(aimAt({ ...world, on: [true, false, true] }, 10.5)).toBeNull()
  })
  it('shows each picture of a look-around for its whole frame', () => {
    const pano: AimPath = { kind: 'rel', t: [0, 0.5, 1.0, 1.5], yaw: [10, 20, 30, 40], pitch: [0, 0, 0, 0], fov: [60, 60, 60, 60], on: [false, true, true, true] }
    expect(aimAt(pano, 0.2)).toBeNull(); expect(aimAt(pano, 0.7)!.yaw).toBe(20); expect(aimAt(pano, 1.49)!.yaw).toBe(30); expect(aimAt(pano, 1.6)!.yaw).toBe(40); expect(aimAt(pano, 2.1)).toBeNull()
    expect(aimAt({ ...pano, viewer: { yaw: 0, pitch: -2, fov: 85 } }, 0.75)!.yaw).toBeCloseTo(25)                                          // (a flat video is interpolated)
  })
})

describe('drawAim', () => {
  const ctx = () => { const calls: string[] = []; const o: Record<string, unknown> = { calls }; return new Proxy(o, { get: (t, k) => k in t ? t[k as string] : (..._a: unknown[]) => { calls.push(String(k)) }, set: () => true }) as unknown as CanvasRenderingContext2D & { calls: string[] } }
  it('clears and draws nothing when the camera is not looking at anything', () => { const c = ctx(); drawAim(c, 640, 360, view(), null); expect(c.calls).toEqual(['clearRect']) })
  it('draws the outline twice (a dark edge under the colour) and the dot with its ring when the aim is in the picture', () => {
    const c = ctx(); drawAim(c, 640, 360, view({ fov: 100 }), { yaw: 5, pitch: 0, fov: 40 }); expect(c.calls.filter(x => x === 'stroke').length).toBeGreaterThanOrEqual(4); expect(c.calls.filter(x => x === 'arc')).toHaveLength(2); expect(c.calls.filter(x => x === 'fill')).toHaveLength(1)
  })
  it('puts a marker on the edge when the aim is out of the picture, and survives a camera wholly behind the viewer', () => {
    const c = ctx(); drawAim(c, 640, 360, view(), { yaw: 80, pitch: 0, fov: 40 }); expect(c.calls.filter(x => x === 'arc')).toHaveLength(1)
    const d = ctx(); expect(() => drawAim(d, 640, 360, view(), { yaw: 180, pitch: 0, fov: 40 })).not.toThrow(); expect(d.calls.filter(x => x === 'arc')).toHaveLength(1)
  })
})
