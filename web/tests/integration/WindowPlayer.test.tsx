import { expect, it, describe, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import WindowPlayer from '../../src/components/WindowPlayer'
import { setup } from '../utils/render'
import { mockGet } from '../utils/api'
import { makeClipDetail } from '../utils/factories'


describe('WindowPlayer', () => {
  it('renders a loading skeleton initially, then renders the player when data loads', async () => {
    mockGet('/api/clip', makeClipDetail({ id: 'c1' }))
    const onClose = vi.fn()
    const { getByText, findByRole } = setup(<WindowPlayer folder="f" clip="c1" start={10} end={20} title="My Window" onClose={onClose} />)

    expect(getByText('My Window')).toBeInTheDocument()

    // initially a skeleton is shown
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument()

    // after fetching, it displays the player
    const player = await findByRole('slider', { name: 'Seek' })           // the clip's own player
    expect(player).toBeInTheDocument()
    expect(document.querySelector('.animate-pulse')).not.toBeInTheDocument()
  })

  it('calls onClose when close button is clicked', async () => {
    mockGet('/api/clip', makeClipDetail())
    const onClose = vi.fn()
    const { getByRole } = setup(<WindowPlayer folder="f" clip="c1" start={10} end={20} title="My Window" onClose={onClose} />)

    const closeBtn = getByRole('button', { name: /close/i })
    await userEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose when Escape is pressed', async () => {
    mockGet('/api/clip', makeClipDetail())
    const onClose = vi.fn()
    setup(<WindowPlayer folder="f" clip="c1" start={10} end={20} title="My Window" onClose={onClose} />)

    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
