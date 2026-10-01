import { describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import FolderBrowser from '../../src/components/FolderBrowser'
import { mockError, mockGet } from '../utils/api'
import type { Browse } from '../../src/api'
import { makeBrowse, makeBrowseEntry } from '../utils/factories'
import { screen, setup } from '../utils/render'

// Serve a folder tree: the response depends on the `path` query parameter (none = the first root).
const serve = (tree: Record<string, Browse>, root = '/data') => mockGet('/api/browse', req => tree[new URL(req.url).searchParams.get('path') ?? root])

describe('FolderBrowser', () => {
  it('lists the sub-folders and marks existing projects', async () => {
    mockGet('/api/browse', makeBrowse({ entries: [makeBrowseEntry({ name: 'plain' }), makeBrowseEntry({ name: 'done', path: '/data/done', is_project: true })] }))
    setup(<FolderBrowser onChoose={vi.fn()} />)
    expect(await screen.findByText('plain')).toBeInTheDocument()
    expect(screen.getByText('done').parentElement).toHaveTextContent('project')
  })

  it('has no accessibility violations once loaded', async () => {
    const { container } = setup(<FolderBrowser onChoose={vi.fn()} />)
    await screen.findByText('/data')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('opens a sub-folder when it is clicked, and goes up with ".."', async () => {
    serve({
      '/data': makeBrowse({ entries: [makeBrowseEntry({ name: 'trip', path: '/data/trip' })] }),
      '/data/trip': makeBrowse({ path: '/data/trip', parent: '/data', entries: [makeBrowseEntry({ name: 'day1', path: '/data/trip/day1' })] }),
    })
    const { user } = setup(<FolderBrowser onChoose={vi.fn()} />)
    await user.click(await screen.findByText('trip'))
    expect(await screen.findByText('day1')).toBeInTheDocument()
    await user.click(screen.getByText('..'))
    expect(await screen.findByText('trip')).toBeInTheDocument()
  })

  it('chooses an existing project straight away instead of showing it', async () => {
    mockGet('/api/browse', makeBrowse({ path: '/data/old', is_project: true }))
    const onChoose = vi.fn()
    setup(<FolderBrowser onChoose={onChoose} />)
    await vi.waitFor(() => expect(onChoose).toHaveBeenCalledWith('/data/old'))
    expect(screen.queryByText('Create project here')).not.toBeInTheDocument()
  })

  it('only offers "Create project here" for a folder with camera files', async () => {
    mockGet('/api/browse', makeBrowse({ can_create: true, footage_here: 3 }))
    const onChoose = vi.fn()
    const { user } = setup(<FolderBrowser onChoose={onChoose} />)
    await user.click(await screen.findByRole('button', { name: 'Create project here' }))
    expect(onChoose).toHaveBeenCalledWith('/data')
    expect(screen.getByText('3 camera file(s) here')).toBeInTheDocument()
  })

  it('disables creation, and says why, when there is nothing to create from', async () => {
    setup(<FolderBrowser onChoose={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Create project here' })).toBeDisabled()
    expect(screen.getByText(/open a folder that holds camera files/)).toBeInTheDocument()
  })

  it('shows the server error when browsing fails', async () => {
    mockError('/api/browse', 403, 'outside the allowed roots')
    setup(<FolderBrowser onChoose={vi.fn()} />)
    expect(await screen.findByText('outside the allowed roots')).toBeInTheDocument()
  })

  it('shows a cancel link only when it can be cancelled', async () => {
    const onCancel = vi.fn()
    const { user, rerender } = setup(<FolderBrowser onChoose={vi.fn()} onCancel={onCancel} />)
    await user.click(await screen.findByRole('button', { name: 'cancel' }))
    expect(onCancel).toHaveBeenCalledOnce()
    rerender(<FolderBrowser onChoose={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'cancel' })).not.toBeInTheDocument()
  })
})
