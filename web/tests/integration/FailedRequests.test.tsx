import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FilmDetails from '../../src/components/FilmDetails'
import RedoDialog from '../../src/components/RedoDialog'
import WindowPlayer from '../../src/components/WindowPlayer'
import { mockError, mockNetworkError, mockPending } from '../utils/api'
import { screen, setup } from '../utils/render'

// A component that asks the server for something and gets no answer (a dropped connection, a 500, the server stopping) must stay as it was and
// stay quiet: an unhandled rejection fails a whole vitest run (it did, on CI, when a request was still in flight as the last test ended).
const rejections: unknown[] = []
const record = (reason: unknown) => { rejections.push(reason) }
beforeEach(() => { rejections.length = 0; process.on('unhandledRejection', record) })
afterEach(() => { process.off('unhandledRejection', record) })
const settle = () => new Promise(r => setTimeout(r, 150))                    // long enough for a rejection to surface (the event fires after the microtask queue drains)

describe.each([
  ['a dropped connection', () => mockNetworkError('/api/meta')],
  ['a server error', () => mockError('/api/meta', 500, 'boom')],
])('FilmDetails with %s', (_n, fail) => {
  it('keeps its skeleton and raises no unhandled rejection', async () => {
    fail(); setup(<FilmDetails folder="/f" />); await settle()
    expect(rejections).toEqual([]); expect(screen.queryByRole('heading', { name: 'Film details' })).not.toBeInTheDocument()
  })
})

describe('RedoDialog when the state cannot be read', () => {
  it.each([['a dropped connection', () => mockNetworkError('/api/state')], ['a server error', () => mockError('/api/state', 500, 'boom')]])('renders nothing and raises no unhandled rejection: %s', async (_n, fail) => {
    fail(); const { container } = setup(<RedoDialog folder="/f" stage="scenes" onClose={vi.fn()} />); await settle()
    expect(rejections).toEqual([]); expect(container).toBeEmptyDOMElement()
  })
})

describe('WindowPlayer when the clip cannot be read', () => {
  it.each([['a dropped connection', () => mockNetworkError('/api/clip')], ['a server error', () => mockError('/api/clip', 404, 'no such clip')]])('raises no unhandled rejection: %s', async (_n, fail) => {
    fail(); setup(<WindowPlayer folder="/f" clip="c1" start={0} end={5} title="A window" onClose={vi.fn()} />); await settle()
    expect(rejections).toEqual([])
  })
})

describe('leaving before the answer arrives', () => {
  it('does not set state after unmount (no warning, no rejection)', async () => {
    mockPending('/api/meta'); const { unmount } = setup(<FilmDetails folder="/f" />); unmount(); await settle(); expect(rejections).toEqual([])
  })
})
