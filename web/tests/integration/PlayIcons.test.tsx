import { expect, it, describe, beforeEach, afterEach, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { act } from '@testing-library/react'
import PlayIcons from '../../src/components/PlayIcons'
import { setup } from '../utils/render'
import { stubMedia } from '../utils/media'

describe('PlayIcons', () => {
  let media: ReturnType<typeof stubMedia>
  let lastAudioEl: HTMLMediaElement | null = null

  beforeEach(() => {
    media = stubMedia()
    lastAudioEl = null
    media.load.mockImplementation(function (this: HTMLMediaElement) {
      lastAudioEl = this
      setTimeout(() => this.dispatchEvent(new Event('loadedmetadata')), 0)
    })
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    if (lastAudioEl) {
      lastAudioEl.dispatchEvent(new Event('ended'))
      lastAudioEl.src = ''
    }
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('renders disabled buttons if audio is not available', () => {
    const { getByRole } = setup(<PlayIcons folder="f" clip="c" t0={1} t1={2} original={false} clean={false} />)
    const btnOrig = getByRole('button', { name: /orig/i })
    const btnClean = getByRole('button', { name: /clean/i })
    expect(btnOrig).toBeDisabled()
    expect(btnOrig).toHaveAttribute('title', 'the sound is not extracted yet')
    expect(btnClean).toBeDisabled()
    expect(btnClean).toHaveAttribute('title', 'the cleaned sound is not made yet')
  })

  it('plays the audio when clicked, and toggles to stop', async () => {
    const { getByRole } = setup(<PlayIcons folder="f" clip="c" t0={1.5} t1={3.5} original={true} clean={true} />)
    const btnOrig = getByRole('button', { name: /orig/i })

    await userEvent.click(btnOrig)
    await vi.advanceTimersByTimeAsync(10)

    expect(media.load).toHaveBeenCalled()
    expect(media.play).toHaveBeenCalled()
    expect(btnOrig.textContent).toMatch(/■/)

    await userEvent.click(btnOrig)
    expect(media.pause).toHaveBeenCalled()
    expect(btnOrig.textContent).toMatch(/▶/)
  })

  it('switches playback between original and clean', async () => {
    const { getByRole } = setup(<PlayIcons folder="f" clip="c" t0={1.5} t1={3.5} original={true} clean={true} />)
    const btnOrig = getByRole('button', { name: /orig/i })
    const btnClean = getByRole('button', { name: /clean/i })

    await userEvent.click(btnOrig)
    await vi.advanceTimersByTimeAsync(10)
    expect(btnOrig.textContent).toMatch(/■/)

    await userEvent.click(btnClean)
    await vi.advanceTimersByTimeAsync(10)

    expect(media.load).toHaveBeenCalledTimes(2)
    expect(media.play).toHaveBeenCalledTimes(2)

    expect(btnOrig.textContent).toMatch(/▶/)
    expect(btnClean.textContent).toMatch(/■/)
  })

  it('stops playback automatically on timeupdate when passing end', async () => {
    const { getByRole } = setup(<PlayIcons folder="f" clip="c" t0={1} t1={2} original={true} clean={true} />)
    const btnOrig = getByRole('button', { name: /orig/i })

    await userEvent.click(btnOrig)
    await vi.advanceTimersByTimeAsync(10)
    expect(btnOrig.textContent).toMatch(/■/)

    act(() => {
      if (lastAudioEl) {
        lastAudioEl.currentTime = 2.1
        lastAudioEl.dispatchEvent(new Event('timeupdate'))
      }
    })

    expect(media.pause).toHaveBeenCalled()
    expect(btnOrig.textContent).toMatch(/▶/)
  })
})
