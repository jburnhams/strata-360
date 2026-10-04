import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ClipPlayer from '../../src/components/ClipPlayer'
import { fireEvent } from '@testing-library/react'
import { screen, setup, waitFor } from '../utils/render'
import { stubBrowserApis, stubMedia } from '../utils/media'

const samples = [{ t: 0, yaw: 10, pitch: 0 }, { t: 1, yaw: 12, pitch: 0 }]
const base = { folder: '/data', clip: 'CAM_1', hasPreview: true, duration: 30 }

describe('ClipPlayer aim menu', () => {
  it('is one drop-down with the three views of you, the other aims and Scenic', () => {
    setup(<ClipPlayer {...base} focus={samples as never} person={samples as never} clarity={samples} scenic={samples} />)
    const menu = screen.getByRole('combobox', { name: 'Where the view points' })
    expect(Array.from(menu.querySelectorAll('option')).map(o => o.textContent)).toEqual(['Free', 'Heading', 'You mid', 'You close', 'You far', 'Person', 'Clarity', 'Scenic'])
    expect(Array.from(menu.querySelectorAll('option')).every(o => !o.disabled)).toBe(true)
    expect(menu).toHaveValue('heading')
  })

  it('disables an aim whose samples the clip does not have yet', () => {
    setup(<ClipPlayer {...base} focus={null} person={null} clarity={null} scenic={null} />)
    const off = Array.from(screen.getByRole('combobox', { name: 'Where the view points' }).querySelectorAll('option')).filter(o => o.disabled).map(o => o.textContent)
    expect(off).toEqual(['You mid', 'You close', 'You far', 'Person', 'Clarity', 'Scenic'])
  })

  it('You close and You far set the field of view the film uses for them', async () => {
    const { user } = setup(<ClipPlayer {...base} focus={samples as never} />)
    const menu = screen.getByRole('combobox', { name: 'Where the view points' }); const fov = () => (screen.getByLabelText(/^view/i) as HTMLInputElement).value
    await user.selectOptions(menu, 'You close'); expect(menu).toHaveValue('you_close'); expect(fov()).toBe('50')
    await user.selectOptions(menu, 'You far'); expect(fov()).toBe('130')
    await user.selectOptions(menu, 'You mid'); expect(fov()).toBe('85')
  })

  it('every aim but Free brings the zoom the film uses for it, and Free keeps the zoom you have', async () => {
    const { user } = setup(<ClipPlayer {...base} focus={samples as never} person={samples as never} clarity={samples} scenic={samples} />)
    const menu = screen.getByRole('combobox', { name: 'Where the view points' }); const fov = () => (screen.getByLabelText(/^view/i) as HTMLInputElement).value
    for (const [name, z] of [['Person', '70'], ['Clarity', '100'], ['Scenic', '100'], ['Heading', '95']]) { await user.selectOptions(menu, name); expect(fov()).toBe(z) }
    await user.selectOptions(menu, 'You close'); await user.selectOptions(menu, 'Free'); expect(fov()).toBe('50')
  })
})

describe('ClipPlayer sound menu', () => {
  it('is there only when the clip has a clean or background sound, and starts on the original', () => {
    const { unmount } = setup(<ClipPlayer {...base} sounds={{ original: true }} />); expect(screen.queryByRole('combobox', { name: 'Which sound' })).toBeNull(); unmount()
    setup(<ClipPlayer {...base} sounds={{ original: true, clean: true, background: false }} />)
    const menu = screen.getByRole('combobox', { name: 'Which sound' }); expect(menu).toHaveValue('original')
    expect(Array.from(menu.querySelectorAll('option')).map(o => [o.textContent, o.disabled])).toEqual([['Original sound', false], ['Clean (speech made clearer)', false], ['Background (without speech)', true]])
    expect(menu).toBeDisabled()                                                                      // until the video has started
  })
})

describe('ClipPlayer: the aim of a point camera drawn over the picture', () => {
  const path = { kind: 'world' as const, t: [0, 10], yaw: [0, 0], pitch: [0, 0], fov: [40, 40], on: [true, true] }
  const arcs: number[] = []
  const gl = new Proxy({} as Record<string, unknown>, { get: (t, k) => (k in t ? t[k as string] : (..._a: unknown[]) => ({})) })
  const ctx2d = new Proxy({} as Record<string, unknown>, { get: (t, k) => (k === 'arc' ? (x: number) => { arcs.push(x) } : k in t ? t[k as string] : () => {}), set: () => true })
  beforeEach(() => {
    arcs.length = 0; stubMedia(); stubBrowserApis()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((type: string) => (type === 'webgl2' ? gl : ctx2d)) as never)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 640 }); Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 360 })
    HTMLElement.prototype.setPointerCapture = vi.fn()
  })
  afterEach(() => { vi.restoreAllMocks(); delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth; delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight })

  it('draws the dot where the camera aims, and keeps it on the same place in the world when you drag the view', async () => {
    const { user } = setup(<ClipPlayer {...base} aimPath={path} />); await user.click(screen.getAllByRole('button', { name: 'Play' })[0])
    await waitFor(() => expect(arcs.length).toBeGreaterThan(1)); const first = arcs.at(-1)!; expect(first).toBeCloseTo(320, 0)                  // (the view looks along the heading, which is where the camera aims: the middle of the 640 px picture)
    const canvas = document.querySelector('canvas:not([data-aim-overlay])') as HTMLCanvasElement
    fireEvent.pointerDown(canvas, { clientX: 300, clientY: 100, pointerId: 1 }); fireEvent.pointerMove(canvas, { clientX: 200, clientY: 100, pointerId: 1 })                  // drag the picture left: you look to the right
    await waitFor(() => expect(arcs.at(-1)!).toBeLessThan(first - 20))                                                                                                    // the place the camera looks at moves left across the picture
    fireEvent.pointerUp(canvas, { pointerId: 1 })
  })

  it('draws nothing when no camera is picked or the video is outside the camera\'s stretch', async () => {
    const { user } = setup(<ClipPlayer {...base} aimPath={{ ...path, t: [100, 110] }} />); await user.click(screen.getAllByRole('button', { name: 'Play' })[0]); await new Promise(r => setTimeout(r, 120)); expect(arcs).toEqual([])
  })

  it('goes to a place in the clip when asked, starting the video first', async () => {
    const seen = vi.spyOn(HTMLMediaElement.prototype, 'currentTime', 'set'); const { rerender } = setup(<ClipPlayer {...base} />)
    rerender(<ClipPlayer {...base} seekTo={{ t: 12.5, n: 1 }} />); const v = document.querySelector('video') as HTMLVideoElement; fireEvent.loadedMetadata(v)
    await waitFor(() => expect(seen).toHaveBeenCalledWith(12.5)); expect(v.getAttribute('src')).toContain('/api/preview')
  })
})
