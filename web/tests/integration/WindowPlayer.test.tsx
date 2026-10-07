import { expect, it, describe, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import WindowPlayer from '../../src/components/WindowPlayer'
import { setup } from '../utils/render'
import { mockGet } from '../utils/api'
import { makeClipDetail } from '../utils/factories'

vi.mock('../../src/components/ClipPlayer', () => ({
  default: () => <div data-testid="clip-player">ClipPlayer Mock</div>
}))

describe('WindowPlayer', () => {
  it('renders a loading skeleton initially, then renders ClipPlayer when data loads', async () => {
    mockGet('/api/clip', makeClipDetail({ id: 'c1' }))
    const onClose = vi.fn()
    const { getByText, findByTestId, container } = setup(<WindowPlayer folder="f" clip="c1" start={10} end={20} title="My Window" onClose={onClose} />)

    expect(getByText('My Window')).toBeInTheDocument()

    // initially a skeleton is shown
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument()

    // after fetching, it displays the player
    const player = await findByTestId('clip-player')
    expect(player).toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).not.toBeInTheDocument()
  })

  it('calls onClose when close button is clicked', async () => {
    mockGet('/api/clip', makeClipDetail())
    const onClose = vi.fn()
    const { getByRole } = setup(<WindowPlayer folder="f" clip="c1" start={10} end={20} title="My Window" onClose={onClose} />)

    const closeBtn = getByRole('button', { name: /close/i })
    await userEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose when background overlay is clicked', async () => {
    mockGet('/api/clip', makeClipDetail())
    const onClose = vi.fn()
    const { container } = setup(<WindowPlayer folder="f" clip="c1" start={10} end={20} title="My Window" onClose={onClose} />)

    const overlay = container.firstChild as HTMLElement
    await userEvent.click(overlay)
    expect(onClose).toHaveBeenCalled()
  })
})
