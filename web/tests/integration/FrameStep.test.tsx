import { describe, expect, it, vi } from 'vitest'
import { fireEvent } from '@testing-library/react'
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
