import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import { cleanup } from '@testing-library/react'
import * as axeMatchers from 'vitest-axe/matchers'
import '@testing-library/jest-dom/vitest'
import { server } from './server'

expect.extend(axeMatchers)

// jsdom (integration project): relative `/api/...` URLs resolve against jsdom's origin, so msw sees them as they are.
// An endpoint without a handler fails the test (see handlers.ts) instead of silently hitting the network.
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => { server.resetHandlers(); cleanup() })
afterAll(() => server.close())
