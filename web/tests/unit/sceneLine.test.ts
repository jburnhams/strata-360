import { describe, expect, it } from 'vitest'
import { sceneLine } from '../../src/sceneLine'

describe('sceneLine: one direction\'s scene labels as a line', () => {
  it('puts the setting, weather, light, water, snow and tags in one line', () => {
    expect(sceneLine({ settings: { forest: 15, trail: 9, mountain: 1, river: 1 }, weather: { fog: 26 }, lighting: { overcast: 24, fog: 2, dusk: 1 }, water: { river: 7 }, ground_snow: 0.96, tags: ['forest', 'snow', 'trees', 'mist', 'trail', 'river'] }))
      .toBe('forest, trail, mountain · fog · overcast, fog · river · snow on the ground (96%) · forest, snow, trees, mist, trail')
  })
  it('leaves out what is not there: no snow under a third of the pictures, nothing for a missing direction', () => {
    expect(sceneLine({ settings: { town: 2 }, ground_snow: 0.1 })).toBe('town'); expect(sceneLine({ settings: {}, weather: {}, tags: [] })).toBe(''); expect(sceneLine(null)).toBe(''); expect(sceneLine(undefined)).toBe('')
    expect(sceneLine({ ground_snow: null, settings: { trail: 1 } })).toBe('trail')
  })
})
