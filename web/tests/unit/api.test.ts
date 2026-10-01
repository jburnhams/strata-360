import { describe, expect, it } from 'vitest'
import { api } from '../../src/api'
import { mockError, mockGet, mockNetworkError, mockPost, recordRequests } from '../utils/api'
import { makeBrowse } from '../utils/factories'

describe('api client', () => {
  it('GETs without a body and returns the parsed JSON', async () => {
    mockGet('/api/last', { folder: '/x' })
    const seen = recordRequests('/api/last')
    expect(await api.last()).toEqual({ folder: '/x' })
    expect(seen).toMatchObject([{ method: 'GET', body: undefined }])
  })

  it('encodes query parameters', async () => {
    const seen = recordRequests('/api/browse')
    await api.browse('/a b/c')
    expect(seen[0].url.search).toBe('?path=%2Fa+b%2Fc')
  })

  it('sends no query at all when browsing the default folder', async () => {
    mockGet('/api/browse', makeBrowse({ path: '/root' }))
    const seen = recordRequests('/api/browse')
    expect((await api.browse()).path).toBe('/root')
    expect(seen[0].url.search).toBe('')
  })

  it('POSTs a JSON body', async () => {
    mockPost('/api/notes', { folder: 'hi', clips: {}, updated: {} })
    const seen = recordRequests('/api/notes')
    await api.saveNote('/f', 'hi', 'c1')
    expect(seen[0]).toMatchObject({ method: 'POST', body: { folder: '/f', text: 'hi', clip: 'c1' } })
  })

  it('throws the server detail on an error response', async () => {
    mockError('/api/roots', 400, 'not a folder')
    await expect(api.roots()).rejects.toThrow('not a folder')
  })

  it('falls back to the status code when the body is not JSON', async () => {
    mockGet('/api/roots', () => { throw new Response('<html>', { status: 502 }) })
    await expect(api.roots()).rejects.toThrow('HTTP 502')
  })

  it('rejects when the connection drops', async () => {
    mockNetworkError('/api/roots')
    await expect(api.roots()).rejects.toThrow()
  })
})
