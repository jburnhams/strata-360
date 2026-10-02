import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setup, screen } from '../utils/render'
import VoiceoverPanel from '../../src/components/VoiceoverPanel'
import { mockGet, mockPost, recordRequests } from '../utils/api'
import { makeVoiceoverState, makeVoiceLine } from '../utils/factories'

describe('VoiceoverPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    // Mock navigator.mediaDevices
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }]
        })
      },
      configurable: true
    })

    // Mock MediaRecorder
    class MockMediaRecorder {
      ondataavailable: ((e: any) => void) | null = null;
      onstop: (() => void) | null = null;
      mimeType = 'audio/webm';
      start() {
        if (this.ondataavailable) {
          this.ondataavailable({ data: new Blob(['audio'], { type: 'audio/webm' }) })
        }
      }
      stop() {
        if (this.onstop) this.onstop()
      }
    }
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)
  })

  it('renders warning when no engine is available', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({ engines: [] }))
    setup(<VoiceoverPanel folder="/data" />)
    expect(await screen.findByText(/The voice model is not installed/i)).toBeInTheDocument()
  })

  it('renders configured state and builds voiceover', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({ lines: 1 }))
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const btn = await screen.findByRole('button', { name: 'Speak the script' })
    const rec = recordRequests('/api/voiceover/build')
    await user.click(btn)

    expect(rec).toHaveLength(1)
    expect(rec[0].body).toEqual({ folder: '/data', engine: 'k', voice: 'v1', rate: 1 })
  })

  it('plays synth voice and uses it', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      timings: { script: 's', engine: 'e', voice: 'v', rate: 1, film_length_s: 1, measured_wpm: 150, over: [], sped: [],
                 lines: [makeVoiceLine({ text: 'Hello', source: 'synth', has_recording: true })] }
    }))
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const btn = await screen.findByRole('button', { name: '▶ voice ✓' })
    const rec = recordRequests('/api/voiceover/use')

    await user.dblClick(btn)

    expect(rec).toHaveLength(1)
    expect(rec[0].body).toEqual({ folder: '/data', seg: 1, use: 'synth' })
  })

  it('records voiceover and stops it', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      timings: { script: 's', engine: 'e', voice: 'v', rate: 1, film_length_s: 1, measured_wpm: 150, over: [], sped: [],
                 lines: [makeVoiceLine({ text: 'Hello', source: 'synth', has_recording: false })] }
    }))
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const recBtn = await screen.findByRole('button', { name: '● record' })
    await user.click(recBtn)

    const stopBtn = await screen.findByRole('button', { name: '■ stop' })
    const rec = recordRequests('/api/voiceover/record')
    await user.click(stopBtn)

    expect(rec).toHaveLength(1)
    expect(rec[0].method).toBe('POST')
    expect(rec[0].url.searchParams.get('seg')).toBe('1')
  })
})
