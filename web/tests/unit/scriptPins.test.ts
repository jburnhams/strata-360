import { describe, expect, it } from 'vitest'
import { addNever, addPin, editNarration, highlight, removeNever, removePin, setMode } from '../../src/scriptPins'

describe('narration pins', () => {
  it('adds a pin anchored to its clip, once', () => {
    const a = addPin({}, '  Say this.  ', '0004'); expect(a.vo).toEqual([{ id: 'v1', text: 'Say this.', mode: 'clip', clip: '0004' }])
    expect(addPin(a, 'say this.', '0004')).toBe(a)                                                           // same text, same clip: not twice
    expect(addPin(a, 'Say this.', '0005').vo).toHaveLength(2)
    expect(addPin({}, '   ', '0004')).toEqual({})
  })

  it('numbers new pins after the existing ones, never reusing an id', () => {
    const p = removePin(addPin(addPin({}, 'one', 'A'), 'two', 'A'), 'v1'); expect(addPin(p, 'three', 'A').vo!.map(x => x.id)).toEqual(['v2', 'v3'])
  })

  it('loosens a pin to in order or anywhere and back, keeping or dropping its clip', () => {
    let p = addPin({}, 'x', '0004'); p = setMode(p, 'v1', 'anywhere'); expect(p.vo![0]).toEqual({ id: 'v1', text: 'x', mode: 'anywhere' })
    p = setMode(p, 'v1', 'clip', '0007'); expect(p.vo![0]).toEqual({ id: 'v1', text: 'x', mode: 'clip', clip: '0007' })
  })

  it('collects never-say phrases without duplicates and removes them', () => {
    const p = addNever(addNever({}, 'best day ever'), 'BEST day ever'); expect(p.vo_never).toEqual(['best day ever']); expect(removeNever(p, 'best day ever').vo_never).toEqual([])
  })

  it('turns an edited narration into a pin and replaces the pins inside the old wording', () => {
    const base = addPin({}, 'old words', '0004'); const edited = editNarration(base, 'Some old words here.', 'Some new words here.', '0004')
    expect(edited.vo!.map(p => p.text)).toEqual(['Some new words here.'])
    expect(editNarration(base, 'same', 'SAME', '0004')).toBe(base)
    expect(editNarration({ vo: [{ id: 'v1', text: 'elsewhere', mode: 'anywhere' }] }, 'a elsewhere b', 'a b', '0004').vo!.map(p => p.text)).toEqual(['a b'])
  })

  it('cuts text into green, red and plain parts', () => {
    const parts = highlight('It was a fine day, a fine day indeed.', ['fine day'], ['indeed'])
    expect(parts.map(p => [p.t, p.kind])).toEqual([['It was a ', undefined], ['fine day', 'must'], [', a ', undefined], ['fine day', 'must'], [' ', undefined], ['indeed', 'never'], ['.', undefined]])
    expect(highlight('plain', [], [])).toEqual([{ t: 'plain', kind: undefined }])
    expect(highlight('abc', ['abc'], ['b']).map(p => p.kind)).toEqual(['must', 'never', 'must'])               // never wins where they overlap
  })
})
