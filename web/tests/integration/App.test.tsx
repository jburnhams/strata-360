import { describe, expect, it, vi } from 'vitest'
import App from '../../src/App'
import { mockError, mockGet, mockPending, recordRequests } from '../utils/api'
import { makeBrowse } from '../utils/factories'
import { screen, setup } from '../utils/render'

// Workspace is a whole screen of its own requests; App only decides which folder to hand it.
vi.mock('../../src/components/Workspace', () => ({ default: ({ folder }: { folder: string }) => <div data-testid="workspace">{folder}</div> }))

describe('App', () => {
  it('shows nothing until it knows whether there is a last project', () => {
    mockPending('/api/last')
    const { container } = setup(<App />)
    expect(container).toBeEmptyDOMElement()
  })

  it('offers the folder browser when there is no last project', async () => {
    setup(<App />)
    expect(await screen.findByText('Open an existing project or create one', { exact: false })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Create project here' })).toBeInTheDocument()
  })

  it('offers the folder browser when asking for the last project fails', async () => {
    mockError('/api/last', 500)
    setup(<App />)
    expect(await screen.findByRole('button', { name: 'Create project here' })).toBeInTheDocument()
  })

  it('creates a project from the browsed folder and tells the server to open it', async () => {
    mockGet('/api/browse', makeBrowse({ path: '/data/trip', can_create: true, footage_here: 2 }))
    const seen = recordRequests('/api/open')
    const { user } = setup(<App />)
    await user.click(await screen.findByRole('button', { name: 'Create project here' }))
    await screen.findByRole('heading', { name: 'Strata 360' })
    await vi.waitFor(() => expect(seen).toMatchObject([{ method: 'POST', body: { folder: '/data/trip' } }]))
    expect(screen.getByTestId('workspace')).toHaveTextContent('/data/trip')
    expect(screen.queryByRole('button', { name: 'Create project here' })).not.toBeInTheDocument()
  })

  it('reopens the last project by itself', async () => {
    mockGet('/api/last', { folder: '/data/last' })
    const seen = recordRequests('/api/open')
    setup(<App />)
    expect(await screen.findByTestId('workspace')).toHaveTextContent('/data/last')
    await vi.waitFor(() => expect(seen).toHaveLength(1))
  })
})
