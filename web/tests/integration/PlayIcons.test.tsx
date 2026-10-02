import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setup, screen } from '../utils/render'
import PlayIcons from '../../src/components/PlayIcons'
import { stubMedia } from '../utils/media'

describe('PlayIcons', () => {
  beforeEach(() => {
    stubMedia()
  })

  it('renders buttons reflecting state', () => {
    setup(<PlayIcons folder="/data" clip="CAM_1" t0={0} t1={5} original={true} clean={false} />)

    const origBtn = screen.getByRole('button', { name: /▶ orig/i })
    expect(origBtn).not.toBeDisabled()

    const cleanBtn = screen.getByRole('button', { name: /▶ clean/i })
    expect(cleanBtn).toBeDisabled()
  })

  it('plays and stops original audio', async () => {
    const { user } = setup(<PlayIcons folder="/data" clip="CAM_1" t0={0} t1={5} original={true} clean={true} />)
    const playSpy = vi.spyOn(window.HTMLAudioElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(window.HTMLAudioElement.prototype, 'load').mockImplementation(function (this: HTMLAudioElement) { this.dispatchEvent(new Event('loadedmetadata')) })
    const pauseSpy = vi.spyOn(window.HTMLAudioElement.prototype, 'pause')

    const origBtn = screen.getByRole('button', { name: /▶ orig/i })
    await user.click(origBtn)

    expect(playSpy).toHaveBeenCalled()
    // Test toggle (stop)
    await user.click(screen.getByRole('button', { name: /■ orig/i }))
    expect(pauseSpy).toHaveBeenCalled()
  })

  it('plays clean audio', async () => {
    const { user } = setup(<PlayIcons folder="/data" clip="CAM_1" t0={0} t1={5} original={true} clean={true} />)
    const playSpy = vi.spyOn(window.HTMLAudioElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(window.HTMLAudioElement.prototype, 'load').mockImplementation(function (this: HTMLAudioElement) { this.dispatchEvent(new Event('loadedmetadata')) })

    const cleanBtn = screen.getByRole('button', { name: /▶ clean/i })
    await user.click(cleanBtn)

    expect(playSpy).toHaveBeenCalled()
  })
})
