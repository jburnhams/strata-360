import { describe, expect, it } from 'vitest'
import { isForeign } from '../../src/components/Phrase'

describe('isForeign', () => {
  it('is false for English', () => { expect(isForeign('en', 'hello', 'hello')).toBe(false) })
  it('is false without a translation', () => { expect(isForeign('fr', 'bonjour', null)).toBe(false) })
  it('is false when the "translation" equals the original apart from spacing', () => { expect(isForeign('fr', 'ok ', ' ok')).toBe(false) })
  it('is true for another language with a different translation', () => { expect(isForeign('fr', 'bonjour', 'hello')).toBe(true) })
})
