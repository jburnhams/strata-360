import { describe, expect, it } from 'vitest'
import { fireEvent } from '@testing-library/react'
import ClipCard from '../../src/components/ClipCard'
import { screen, setup } from '../utils/render'
import { makeTrackClip } from '../utils/factories'

describe('ClipCard', () => {
  it('shows the clip\'s picture and where in the race it is', () => {
    const { container } = setup(<ClipCard folder="/data" clip={makeTrackClip()} overlay={false} />)
    expect(container.querySelector('img')).toHaveAttribute('src', expect.stringContaining('/api/thumb?')); expect(screen.getByText('clip 0023')).toBeInTheDocument(); expect(screen.getByText(/Sun 22 Feb 20:01/)).toBeInTheDocument()
    expect(screen.getByText('3 min')).toBeInTheDocument()
    expect(screen.getByText('km 12.3 (16%)')).toBeInTheDocument(); expect(screen.getByText('5:45 /km')).toBeInTheDocument(); expect(screen.getByText('+4%')).toBeInTheDocument(); expect(screen.getByText('569 m')).toBeInTheDocument()
    expect(screen.getByText('141')).toBeInTheDocument(); expect(screen.getByText('trail, fog')).toBeInTheDocument(); expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('says whether the newest script draft plays the clip', () => {
    const { rerender } = setup(<ClipCard folder="/data" clip={makeTrackClip()} overlay={false} />); expect(screen.getByText('in the film · 16.5 s')).toBeInTheDocument()
    rerender(<ClipCard folder="/data" clip={makeTrackClip({ used: false, used_s: 0 })} overlay={false} />); expect(screen.getByText('not in the film')).toBeInTheDocument()
  })

  it('says "stopped or very slow" where there is no pace, and uses the overlay thumbnail when asked', () => {
    const { container } = setup(<ClipCard folder="/data" clip={makeTrackClip({ facts: { ...makeTrackClip().facts!, pace_min_km: null } })} overlay />)
    expect(screen.getByText('stopped or very slow')).toBeInTheDocument(); expect(container.querySelector('img')).toHaveAttribute('src', expect.stringContaining('overlay=1'))
  })

  it('hides a thumbnail that cannot be loaded', () => {
    const { container } = setup(<ClipCard folder="/data" clip={makeTrackClip()} overlay={false} />); const img = container.querySelector('img')!; fireEvent.error(img); expect(img.style.display).toBe('none')
  })

  it('shows a short clip\'s length in seconds', () => {
    setup(<ClipCard folder="/data" clip={makeTrackClip({ duration_s: 12 })} overlay={false} />); expect(screen.getByText('12 s')).toBeInTheDocument()
  })
})
