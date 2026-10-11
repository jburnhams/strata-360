import { describe, expect, it } from 'vitest'
import { vfovDeg, wrapDeg, aimPitch, Follower } from '../../src/aim'

describe('vfovDeg', () => {
  it('calculates vertical field of view correctly based on horizontal fov and aspect ratio', () => {
    // 90 degrees horizontal with 16:9 aspect ratio should be around 58.7 degrees vertical
    expect(vfovDeg(90)).toBeCloseTo(58.71, 1)

    // 120 degrees horizontal with 4:3 aspect ratio
    expect(vfovDeg(120, 4 / 3)).toBeCloseTo(104.8, 1)
  })
})

describe('wrapDeg', () => {
  it('wraps angles between -180 and 180 degrees', () => {
    expect(wrapDeg(0)).toBeCloseTo(0)
    expect(wrapDeg(180)).toBeCloseTo(-180)
    expect(wrapDeg(-180)).toBeCloseTo(-180)
    expect(wrapDeg(350)).toBeCloseTo(-10)
    expect(wrapDeg(-350)).toBeCloseTo(10)
    expect(wrapDeg(360)).toBeCloseTo(0)
    expect(wrapDeg(-360)).toBeCloseTo(0)
    expect(wrapDeg(400)).toBeCloseTo(40)
    expect(wrapDeg(-400)).toBeCloseTo(-40)
  })
})

describe('aimPitch', () => {
  it('keeps the whole head in frame with given margins', () => {
    const HEAD_MARGIN = 0.08
    const BAND_PITCH = 3.5
    // Top of head is pitch + height/2 (e.g. 0 + 45/2 = 22.5)
    // Lowest aim = 22.5 - (0.5 - 0.08)*90 + 3.5 = 22.5 - 37.8 + 3.5 = -11.8
    // Since pitch is 0, max(-11.8, 0) is 0
    expect(aimPitch(0, 45, 90)).toBe(0)

    // With explicit headTop
    // Top of head = 30
    // Lowest aim = 30 - (0.5 - 0.08)*100 + 3.5 = 30 - 42 + 3.5 = -8.5
    // max(-8.5, 0) = 0
    expect(aimPitch(0, 45, 100, 30)).toBe(0)

    // If the person is very high up, lowest aim will be higher than pitch
    // Top of head = 50 + 20/2 = 60
    // Lowest aim = 60 - (0.5 - 0.08)*60 + 3.5 = 60 - 25.2 + 3.5 = 38.3
    // max(38.3, 20) = 38.3
    expect(aimPitch(20, 20, 60, 60)).toBeCloseTo(38.3, 1)

    // If vfov is small, lowest aim will be higher than pitch
    // Top of head = 0 + 45/2 = 22.5
    // Lowest aim = 22.5 - (0.5 - 0.08)*30 + 3.5 = 22.5 - 12.6 + 3.5 = 13.4
    // pitch argument is 0, so max(13.4, 0) = 13.4
    expect(aimPitch(0, 45, 30)).toBeCloseTo(13.4, 1)
  })
})

describe('Follower', () => {
  it('starts in hold mode and stays there if target is near center', () => {
    const f = new Follower(0, 0)
    // Small step, doesn't exceed BAND_YAW (9) or BAND_PITCH (3.5)
    f.step(2, 1, 0.1)
    expect(f.y).toBeCloseTo(0)
    expect(f.p).toBeCloseTo(0)
  })

  it('enters pan mode after holding out of deadband for HOLD_S', () => {
    const f = new Follower(0, 0)
    // Target moves out of deadband
    f.step(15, 0, 0.3) // Time hasn't exceeded HOLD_S (0.5)
    expect(f.y).toBeCloseTo(0)

    f.step(15, 0, 0.3) // Exceeds HOLD_S
    // Now it should be in pan mode and start panning
    f.step(15, 0, 0.1)
    expect(f.y).toBeGreaterThan(0)
  })

  it('settles down to hold mode when target gets near center again', () => {
    const f = new Follower(0, 0)
    // Go into pan mode
    f.step(15, 0, 0.6)
    f.step(15, 0, 2.0) // Pan towards 15
    expect(f.y).toBeGreaterThan(10)

    // Now target is very close to current aim (within SETTLE * deadband = 0.3 * 9 = 2.7)
    // Next step will transition to hold
    f.step(f.y, f.p, 0.1)

    // The velocities decay exponentially in hold mode
    const oldY = f.y
    f.step(f.y, f.p, 1.0)
    expect(f.y - oldY).toBeLessThan(1.0) // Has decayed and stopped moving much
  })

  it('enters jump mode when target is far away for JUMP_AFTER_S and executes jump curve', () => {
    const f = new Follower(0, 0)
    // Target jumps far away (JUMP_DEG = 28)
    f.step(30, 0, 0.2) // Not long enough (JUMP_AFTER_S = 0.3)
    expect(f.y).toBeCloseTo(0)

    // Exceeds JUMP_AFTER_S, sets up jump on this frame
    f.step(30, 0, 0.2)

    // Run steps to complete the jump (JUMP_S is 0.5)
    f.step(30, 0, 0.25) // Halfway through the jump duration
    expect(f.y).toBeGreaterThan(10)
    expect(f.y).toBeLessThan(30)

    f.step(30, 0, 0.3) // Completes the jump (total time >= 0.5)
    expect(f.y).toBeCloseTo(30)

    // Should be back to hold mode
    const oldY = f.y
    f.step(30, 0, 0.1)
    expect(f.y).toBeCloseTo(oldY) // In hold mode it doesn't move towards current target much anymore
  })

  it('wraps the yaw properly while panning', () => {
    const f = new Follower(170, 0)
    // Target is at -170, which is +20 degrees away wrapping around
    f.step(-170, 0, 0.6) // Pan mode trigger
    f.step(-170, 0, 1.0)

    // Follower just operates on raw y.
    // So if it pans towards -170 starting from 170, ey is 20.
    // It will increase y to 190.
    expect(f.y).toBeGreaterThan(170)
  })
})
