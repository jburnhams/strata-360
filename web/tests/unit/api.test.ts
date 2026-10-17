import { describe, expect, it } from 'vitest'
import { api } from '../../src/api'
import { mockError, mockGet, mockDelete, mockNetworkError, mockPost, recordRequests } from '../utils/api'
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

describe('url builders', () => {
  it('photoMotionVideo builds correct URL', () => {
    expect(api.photoMotionVideo('f', 'id1', { style: 'pan', seconds: 5, seed: 123 })).toBe('/api/photos/motion/video?folder=f&id=id1&style=pan&seconds=5&seed=123&w=960')
    expect(api.photoMotionVideo('f', 'id1', { style: 'pan', seconds: 5, seed: 123 }, 480)).toBe('/api/photos/motion/video?folder=f&id=id1&style=pan&seconds=5&seed=123&w=480')
  })
  it('photoThumb builds correct URL', () => {
    expect(api.photoThumb('f', 'id1')).toBe('/api/photos/thumb?folder=f&id=id1&w=480')
    expect(api.photoThumb('f', 'id1', 200)).toBe('/api/photos/thumb?folder=f&id=id1&w=200')
  })
  it('photoOverlay builds correct URL', () => {
    expect(api.photoOverlay('f', 'id1')).toBe('/api/photos/thumb?folder=f&id=id1&overlay=1')
  })
  it('photoFile builds correct URL', () => {
    expect(api.photoFile('f', 'id1')).toBe('/api/photos/file?folder=f&id=id1')
  })
  it('previewUrl builds correct URL', () => {
    expect(api.previewUrl('f', 'c1')).toBe('/api/preview?folder=f&clip=c1')
  })
  it('thumbUrl builds correct URL', () => {
    expect(api.thumbUrl('f', 'c1', 'v1')).toBe('/api/thumb?folder=f&clip=c1&v=v1')
    expect(api.thumbUrl('f', 'c1', 'v1', true)).toBe('/api/thumb?folder=f&clip=c1&v=v1&overlay=1')
  })
  it('objectUrl builds correct URL', () => {
    expect(api.objectUrl('f', 'c1', 12)).toBe('/api/clip/object?folder=f&clip=c1&id=12')
  })
  it('clipAudioUrl builds correct URL', () => {
    expect(api.clipAudioUrl('f', 'c1', 'clean')).toBe('/api/clip/audio?folder=f&clip=c1&kind=clean')
  })
  it('voiceoverAudio builds correct URL', () => {
    expect(api.voiceoverAudio('f', 1)).toBe('/api/voiceover/audio?folder=f&seg=1&source=synth')
    expect(api.voiceoverAudio('f', 1, 'recorded')).toBe('/api/voiceover/audio?folder=f&seg=1&source=recorded')
    expect(api.voiceoverAudio('f', undefined, undefined, 't1')).toBe('/api/voiceover/audio?folder=f&track=t1')
  })
  it('filmUrl builds correct URL', () => {
    expect(api.filmUrl('f')).toBe('/api/film/index.m3u8?folder=f')
  })
  it('filmStillThumbUrl builds correct URL', () => {
    expect(api.filmStillThumbUrl('f', 'name')).toBe('/api/film/still/thumb?folder=f&name=name&w=320')
  })
  it('filmStillUrl builds correct URL', () => {
    expect(api.filmStillUrl('f', 'name')).toBe('/api/film/still/file?folder=f&name=name')
  })
  it('finalUrl builds correct URL', () => {
    expect(api.finalUrl('f')).toBe('/api/final/file?folder=f')
  })
  it('musicAudioUrl builds correct URL', () => {
    expect(api.musicAudioUrl('f')).toBe('/api/music/audio?folder=f')
  })
  it('musicSpectrogramUrl builds correct URL', () => {
    expect(api.musicSpectrogramUrl('f', 'v1')).toBe('/api/music/spectrogram?folder=f&v=v1')
  })
  it('builtMusicUrl builds correct URL', () => {
    expect(api.builtMusicUrl('f', 'v1')).toBe('/api/music/built/audio?folder=f&v=v1')
  })
  it('whoSheetUrl builds correct URL', () => {
    expect(api.whoSheetUrl('f', 1)).toBe('/api/who/sheet?folder=f&v=1')
  })
  it('whoMeUrl builds correct URL', () => {
    expect(api.whoMeUrl('f', 1)).toBe('/api/who/me?folder=f&v=1')
  })
  it('roughMixUrl builds correct URL', () => {
    expect(api.roughMixUrl('f', 'v1')).toBe('/api/script2/mix/audio?folder=f&v=v1')
  })
})

describe('fetch methods', () => {
  it('uploadPhoto calls POST /api/photos and handles error', async () => {
    const file = new File([''], 'test.jpg')
    mockPost('/api/photos', { id: 'p1' })
    const res = await api.uploadPhoto('f', file)
    expect(res).toEqual({ id: 'p1' })

    mockError('/api/photos', 400, 'Bad image', 'post')
    await expect(api.uploadPhoto('f', file)).rejects.toThrow('Bad image')
  })

  it('deletePhoto calls DELETE /api/photos and handles error', async () => {
    mockDelete('/api/photos', () => new Response(null, { status: 204 }))
    let reqs = recordRequests('/api/photos')
    await api.deletePhoto('f', 'p1')
    expect(reqs[0]?.method).toBe('DELETE')

    mockError('/api/photos', 500, 'Failed to delete photo', 'delete')
    // the deletePhoto method actually only throws HTTP <status> because it doesn't parse JSON, so we expect HTTP 500
    await expect(api.deletePhoto('f', 'p1')).rejects.toThrow('HTTP 500')
  })

  it('removeTrack calls DELETE /api/tracks and handles error', async () => {
    mockDelete('/api/tracks', { test: 1 })
    let reqs = recordRequests('/api/tracks')
    await api.removeTrack('f', 't1')
    expect(reqs[0]?.method).toBe('DELETE')

    mockError('/api/tracks', 500, 'Failed to remove track', 'delete')
    await expect(api.removeTrack('f', 't1')).rejects.toThrow('Failed to remove track')
  })

  it('resetLyrics calls DELETE /api/lyrics', async () => {
    mockDelete('/api/lyrics', () => new Response(null, { status: 204 }))
    let reqs = recordRequests('/api/lyrics')
    await api.resetLyrics('f')
    expect(reqs[0]?.method).toBe('DELETE')
  })

  it('resetRoughMix calls DELETE /api/script2/mix', async () => {
    mockDelete('/api/script2/mix', () => new Response(null, { status: 204 }))
    let reqs = recordRequests('/api/script2/mix')
    await api.resetRoughMix('f')
    expect(reqs[0]?.method).toBe('DELETE')
  })

  it('recordVoiceover calls POST /api/voiceover/record and handles error', async () => {
    const file = new Blob([''], { type: 'audio/webm' })
    mockPost('/api/voiceover/record', {})
    let reqs = recordRequests('/api/voiceover/record')
    await api.recordVoiceover('f', 1, file)
    expect(reqs[0]?.method).toBe('POST')

    mockError('/api/voiceover/record', 500, 'Error', 'post')
    await expect(api.recordVoiceover('f', 1, file)).rejects.toThrow('Error')
  })

  it('deleteRecording calls DELETE /api/voiceover/record', async () => {
    mockDelete('/api/voiceover/record', () => new Response(null, { status: 204 }))
    let reqs = recordRequests('/api/voiceover/record')
    await api.deleteRecording('f', 1)
    expect(reqs[0]?.method).toBe('DELETE')
  })

  it('uploadMusic calls POST /api/music and handles error', async () => {
    const file = new File([''], 'test.mp3')
    mockPost('/api/music', { test: 1 })
    const res = await api.uploadMusic('f', file)
    expect(res).toEqual({ test: 1 })

    mockError('/api/music', 500, 'Error', 'post')
    await expect(api.uploadMusic('f', file)).rejects.toThrow('Error')
  })

  it('removeMusic calls DELETE /api/music', async () => {
    mockDelete('/api/music', () => new Response(null, { status: 204 }))
    let reqs = recordRequests('/api/music')
    await api.removeMusic('f')
    expect(reqs[0]?.method).toBe('DELETE')
  })
})
