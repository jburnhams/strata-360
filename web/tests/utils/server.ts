import { setupServer } from 'msw/node'
import { handlers } from './handlers'

/** One shared msw server for every test; see handlers.ts for the defaults and api.ts for per-test overrides. */
export const server = setupServer(...handlers)
