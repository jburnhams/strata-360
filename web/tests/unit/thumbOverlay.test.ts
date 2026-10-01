import { describe, expect, it } from 'vitest'
import { api } from '../../src/api'
import { setThumbOverlay, thumbOverlay, thumbVersion } from '../../src/thumbOverlay'

describe('thumbnail overlay switch', () => {
  it('starts off and can be turned on and off without storage (node has none)', () => {
    expect(thumbOverlay()).toBe(false)
    setThumbOverlay(true); expect(thumbOverlay()).toBe(true)
    setThumbOverlay(false); expect(thumbOverlay()).toBe(false)
  })

  it('changes the thumbnail version only when the overlay picture exists and is wanted', () => {
    expect(thumbVersion({ thumb: 'best', thumb_overlay: true }, true)).toBe('best+overlay')
    expect(thumbVersion({ thumb: 'best', thumb_overlay: true }, false)).toBe('best')
    expect(thumbVersion({ thumb: 'quick', thumb_overlay: false }, true)).toBe('quick')
    expect(thumbVersion({ thumb: 'quick' }, true)).toBe('quick')
  })
})

describe('api.thumbUrl', () => {
  it('asks for the overlay version only when told to', () => {
    expect(api.thumbUrl('/f', 'c1', 'best')).toBe('/api/thumb?folder=%2Ff&clip=c1&v=best')
    expect(api.thumbUrl('/f', 'c1', 'best+overlay', true)).toBe('/api/thumb?folder=%2Ff&clip=c1&v=best%2Boverlay&overlay=1')
  })
})
