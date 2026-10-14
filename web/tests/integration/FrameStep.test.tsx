import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { act, fireEvent } from '@testing-library/react'
import { screen, setup } from '../utils/render'
import StepVideo, { stepFrame } from '../../src/components/FrameStep'
import PanoPlayer from '../../src/components/PanoPlayer'

const fakeVideo = (t: number, duration = 10) => { const v = document.createElement('video'); v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: duration, configurable: true }); v.currentTime = t; return v }

describe('stepping a video one frame at a time', () => {
  it('pauses and moves to the next and the previous frame on the frame grid, within the video', () => {
    const v = fakeVideo(1.0, 2); stepFrame(v, 1, 0.25); expect(v.pause).toHaveBeenCalled(); expect(v.currentTime).toBeCloseTo(1.25 + 0.0625, 3)
    stepFrame(v, -1, 0.25); expect(v.currentTime).toBeCloseTo(1.0 + 0.0625, 3); stepFrame(fakeVideo(0, 2), -1, 0.25); const a = fakeVideo(0, 2); stepFrame(a, -1, 0.25); expect(a.currentTime).toBe(0)
    const e = fakeVideo(1.99, 2); stepFrame(e, 1, 0.25); expect(e.currentTime).toBeLessThanOrEqual(2); stepFrame(null, 1, 0.25)
  })

  it('puts the frame buttons under a video and they step it', async () => {
    const { user } = setup(<StepVideo src="/x.mp4" aria-label="A clip" />); const v = screen.getByLabelText('A clip') as HTMLVideoElement; v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: 10, configurable: true })
    await user.click(screen.getByRole('button', { name: 'Next frame' })); expect(v.pause).toHaveBeenCalled(); expect(v.currentTime).toBeGreaterThan(0)
    const t = v.currentTime; await user.click(screen.getByRole('button', { name: 'Previous frame' })); expect(v.currentTime).toBeLessThan(t)
  })

  it('has the frame buttons on the 360 player too, stepping by the rate of the original pictures', async () => {
    const { user, container } = setup(<PanoPlayer src="/p.mp4" label="M1" fps={4} />); const v = container.querySelector('video') as HTMLVideoElement; v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: 9, configurable: true })
    fireEvent.loadedMetadata(v); await user.click(screen.getByRole('button', { name: 'Next frame' })); expect(v.currentTime).toBeCloseTo(0.25 + 0.0625, 3)
  })
})


describe('learning the length of a frame', () => {
  type Cb = (now: number, m: { mediaTime: number }) => void
  const proto = HTMLVideoElement.prototype as unknown as Record<string, unknown>
  let pending: Cb | null; let cancelled: number[]
  beforeEach(() => {
    pending = null; cancelled = []
    Object.defineProperty(proto, 'requestVideoFrameCallback', { configurable: true, writable: true, value: (cb: Cb) => { pending = cb; return 7 } })
    Object.defineProperty(proto, 'cancelVideoFrameCallback', { configurable: true, writable: true, value: (id: number) => { cancelled.push(id) } })
  })
  afterEach(() => { delete proto.requestVideoFrameCallback; delete proto.cancelVideoFrameCallback })
  const show = (mediaTime: number) => act(() => { pending!(0, { mediaTime }) })
  const stepFrom = async (user: ReturnType<typeof setup>['user'], v: HTMLVideoElement, t: number) => { v.currentTime = t; await user.click(screen.getByRole('button', { name: 'Next frame' })); return v.currentTime }

  it('steps by the shortest gap between the frames the video shows', async () => {
    const { user } = setup(<StepVideo src="/x.mp4" aria-label="A clip" />); const v = screen.getByLabelText('A clip') as HTMLVideoElement; v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: 60, configurable: true })
    show(0); show(0.04); show(0.12); show(0.14)                                  // gaps of 0.04, 0.08 and 0.02: the shortest is one frame
    expect(await stepFrom(user, v, 1.0)).toBeCloseTo(51 * 0.02 + 0.005, 4)
  })

  it('ignores a repeated frame time and the first frame it sees', async () => {
    const { user } = setup(<StepVideo src="/x.mp4" aria-label="A clip" />); const v = screen.getByLabelText('A clip') as HTMLVideoElement; v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: 60, configurable: true })
    show(5.0); show(5.0); show(5.04)
    expect(await stepFrom(user, v, 1.0)).toBeCloseTo(26 * 0.04 + 0.01, 4)        // (a gap of 0 is a repeat, not a frame)
  })

  it('steps by 1/30 s until it has learnt anything', async () => {
    const { user } = setup(<StepVideo src="/x.mp4" aria-label="A clip" />); const v = screen.getByLabelText('A clip') as HTMLVideoElement; v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: 60, configurable: true })
    expect(await stepFrom(user, v, 1.0)).toBeCloseTo(31 / 30 + 1 / 120, 4)
  })

  it('forgets what it learnt when the video changes, and stops watching when it goes', async () => {
    const { rerender, unmount } = setup(<StepVideo src="/a.mp4" aria-label="A clip" />)
    const v = screen.getByLabelText('A clip') as HTMLVideoElement; v.pause = vi.fn(); Object.defineProperty(v, 'duration', { value: 60, configurable: true })
    show(0); show(0.02); rerender(<StepVideo src="/b.mp4" aria-label="A clip" />)
    const user = userEvent.setup(); expect(await stepFrom(user, v, 1.0)).toBeCloseTo(31 / 30 + 1 / 120, 4)
    expect(cancelled.length).toBeGreaterThan(0); unmount(); expect(cancelled.at(-1)).toBe(7)
  })
})
