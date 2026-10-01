import type { AxeMatchers } from 'vitest-axe/matchers'

// Types for `expect(await axe(container)).toHaveNoViolations()` (registered in setup.ts).
declare module 'vitest' {
  interface Assertion<T = any> extends AxeMatchers {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}
