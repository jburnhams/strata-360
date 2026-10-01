import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../src/api'

const reply = (ok: boolean, status: number, body: unknown) => vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) })

afterEach(() => { vi.unstubAllGlobals() })

describe('api client', () => {
  it('GETs without a body and returns the parsed JSON', async () => {
    const f = reply(true, 200, { folder: '/x' }); vi.stubGlobal('fetch', f)
    expect(await api.last()).toEqual({ folder: '/x' })
    expect(f).toHaveBeenCalledWith('/api/last', undefined)
  })

  it('encodes query parameters', async () => {
    const f = reply(true, 200, {}); vi.stubGlobal('fetch', f)
    await api.browse('/a b/c')
    expect(f.mock.calls[0][0]).toBe('/api/browse?path=%2Fa+b%2Fc')
  })

  it('throws the server detail on an error response', async () => {
    vi.stubGlobal('fetch', reply(false, 400, { detail: 'not a folder' }))
    await expect(api.roots()).rejects.toThrow('not a folder')
  })

  it('falls back to the status code when the body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: () => Promise.reject(new Error('bad json')) }))
    await expect(api.roots()).rejects.toThrow('HTTP 502')
  })
})
