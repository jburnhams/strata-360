import { describe, expect, it } from 'vitest'
import ClipPlayer from '../../src/components/ClipPlayer'
import { screen, setup } from '../utils/render'

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
