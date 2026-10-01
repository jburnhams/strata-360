import { afterEach, describe, expect, it } from 'vitest'
import { setThumbOverlay, useThumbOverlay } from '../../src/thumbOverlay'
import { act, screen, setup } from '../utils/render'

function Switch({ label }: { label: string }) {
  const [on, set] = useThumbOverlay()
  return <label><input type="checkbox" checked={on} onChange={e => set(e.target.checked)} />{label}</label>
}

describe('useThumbOverlay', () => {
  afterEach(() => { act(() => setThumbOverlay(false)); localStorage.clear() })

  it('turning it on in one place turns it on everywhere and remembers it', async () => {
    const { user } = setup(<><Switch label="list" /><Switch label="player" /></>)
    await user.click(screen.getByLabelText('list'))
    expect(screen.getByLabelText('player')).toBeChecked()
    expect(localStorage.getItem('strata360.thumbOverlay')).toBe('1')
  })

  it('turning it off is remembered too', async () => {
    act(() => setThumbOverlay(true))
    const { user } = setup(<Switch label="list" />)
    await user.click(screen.getByLabelText('list'))
    expect(screen.getByLabelText('list')).not.toBeChecked()
    expect(localStorage.getItem('strata360.thumbOverlay')).toBe('0')
  })
})
