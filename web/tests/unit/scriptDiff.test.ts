import { describe, expect, it } from 'vitest'
import type { ScriptItem } from '../../src/api'
import { diffDrafts, itemKey } from '../../src/scriptDiff'

const vo = (clip: string, text: string): ScriptItem => ({ type: 'vo', clip, text })
const clip = (c: string, from: string, to: string): ScriptItem => ({ type: 'clip', clip: c, from, to })
const broll = (c: string, seconds: number): ScriptItem => ({ type: 'broll', clip: c, seconds })

describe('diffDrafts', () => {
  it('says nothing is new when there is no previous draft', () => {
    const d = diffDrafts(undefined, [vo('0001', 'a')]); expect(d.added.size).toBe(0); expect(d.removed).toEqual([])
  })

  it('finds new and removed items and ignores the ones that did not change', () => {
    const prev = [vo('0001', 'one'), clip('0002', '0002.00', '0002.01'), broll('0003', 5)]
    const cur = [vo('0001', 'one'), clip('0002', '0002.00', '0002.02'), broll('0003', 5.2), vo('0004', 'new')]
    const d = diffDrafts(prev, cur)
    expect([...d.added]).toEqual([1, 3])
    expect(d.removed).toEqual([clip('0002', '0002.00', '0002.01')])
  })

  it('matches repeated items one for one', () => {
    const d = diffDrafts([broll('0001', 4), broll('0001', 4)], [broll('0001', 4), broll('0001', 4), broll('0001', 4)])
    expect([...d.added]).toEqual([2]); expect(d.removed).toEqual([])
  })

  it('keys a sing item by its picture and its phrase', () => {
    const sing = (clip: string, phrase: string) => ({ type: 'sing', clip, phrase, seconds: 9.9 }) as never
    expect(itemKey(sing('0002', 'L01'))).toBe(itemKey(sing('0002', 'L01'))); expect(itemKey(sing('0002', 'L01'))).not.toBe(itemKey(sing('0002', 'L02')))
  })
  it('keys b-roll by whole seconds', () => { expect(itemKey(broll('0001', 4.4))).toBe(itemKey(broll('0001', 3.6))) })
})
