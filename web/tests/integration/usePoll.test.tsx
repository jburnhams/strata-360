import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { usePoll } from '../../src/usePoll'

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('usePoll', () => {
  it('fetches at once and then on every interval', async () => {
    let n = 0; const fn = vi.fn(() => Promise.resolve(++n))
    const { result } = renderHook(() => usePoll(fn, 1000, []))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current).toBe(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(result.current).toBe(2)
  })

  it('keeps the last good value when a poll fails', async () => {
    const fn = vi.fn().mockResolvedValueOnce('ok').mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => usePoll(fn, 1000, []))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(result.current).toBe('ok')
  })

  it('stops polling on unmount', async () => {
    const fn = vi.fn(() => Promise.resolve(1))
    const { unmount } = renderHook(() => usePoll(fn, 1000, []))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    unmount()
    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
