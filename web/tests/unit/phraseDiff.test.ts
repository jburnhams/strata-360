import { describe, expect, it } from 'vitest'
import { diffPhrase } from '../../src/phraseDiff'

const words = (...ws: string[]) => ws.map((w, i) => ({ i, w }))

describe('diffPhrase', () => {
  it('changes nothing when the text is the same', () => { expect(diffPhrase(words('we', 'are', 'fine'), 'we are fine')).toEqual([]) })
  it('ignores extra spaces', () => { expect(diffPhrase(words('we', 'are'), '  we   are ')).toEqual([]) })
  it('replaces one word for one word', () => { expect(diffPhrase(words('we', 'wear', 'fine'), 'we are fine')).toEqual([{ i: 1, text: 'are' }]) })
  it('counts a change of punctuation or case as a change of that word', () => { expect(diffPhrase(words('so', 'I', 'was'), 'So I was,')).toEqual([{ i: 0, text: 'So' }, { i: 2, text: 'was,' }]) })
  it('replaces the words of a stretch one for one when the counts match', () => { expect(diffPhrase(words('a', 'b', 'c', 'd'), 'a x y d')).toEqual([{ i: 1, text: 'x' }, { i: 2, text: 'y' }]) })
  it('puts a longer replacement on the first word and empties the rest of the stretch', () => {
    expect(diffPhrase(words('a', 'b', 'c', 'd'), 'a x y z d')).toEqual([{ i: 1, text: 'x y z' }, { i: 2, text: '' }])
  })
  it('puts a shorter replacement on the first word and empties the rest', () => { expect(diffPhrase(words('a', 'b', 'c', 'd'), 'a x d')).toEqual([{ i: 1, text: 'x' }, { i: 2, text: '' }]) })
  it('empties a deleted word', () => { expect(diffPhrase(words('up', 'up', 'here'), 'up here')).toEqual([{ i: 1, text: '' }]) })
  it('tacks an added word onto the word before it', () => { expect(diffPhrase(words('i', 'did', 'back'), 'i did get back')).toEqual([{ i: 1, text: 'did get' }]) })
  it('puts words added at the start in front of the first word', () => { expect(diffPhrase(words('did', 'get', 'back'), 'we did get back')).toEqual([{ i: 0, text: 'we did' }]) })
  it('adds words after the last word', () => { expect(diffPhrase(words('on', 'path'), 'on path now')).toEqual([{ i: 1, text: 'path now' }]) })
  it('keeps a model-corrected word that holds several tokens when they are still there', () => { expect(diffPhrase(words('fell', 'in the', 'river'), 'fell in the river')).toEqual([]) })
  it('edits inside a multi-token word', () => { expect(diffPhrase(words('fell', 'in the', 'river'), 'fell in a river')).toEqual([{ i: 1, text: 'in a' }]) })
  it('skips hidden (empty) words and keeps them hidden', () => { expect(diffPhrase(words('a', '', 'c'), 'a c')).toEqual([]) })
  it('puts text typed into a phrase of hidden words on the first word', () => { expect(diffPhrase(words('', ''), 'hello')).toEqual([{ i: 0, text: 'hello' }]) })
  it('empties every word when the text is cleared', () => { expect(diffPhrase(words('a', 'b'), '')).toEqual([{ i: 0, text: '' }, { i: 1, text: '' }]) })
})
