import { describe, it, expect, vi } from 'vitest'
import { axe } from 'vitest-axe'
import userEvent from '@testing-library/user-event'
import { setup, screen, waitFor } from '../utils/render'
import { mockGet, mockPost, recordRequests, mockPending, mockError } from '../utils/api'
import { makeVoiceoverState } from '../utils/factories'
import VoiceoverPanel from '../../src/components/VoiceoverPanel'
import { stubMedia } from '../utils/media'

stubMedia()

describe('VoiceoverPanel', () => {
  it('renders a skeleton while loading', () => {
    mockPending('/api/voiceover')
    setup(<VoiceoverPanel folder="/data" />)
    expect(screen.getByText('Voice-over audio')).toBeInTheDocument()
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
  })

  it('shows missing engine warning if no engines are installed', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({ engines: [] }))
    setup(<VoiceoverPanel folder="/data" />)
    expect(await screen.findByText(/The voice model is not installed/)).toBeInTheDocument()
  })

  it('builds a voiceover track with selected settings', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      engines: [{ id: 'e1', label: 'E1', voices: [{ name: 'v1', lang: 'en' }, { name: 'v2', lang: 'en' }] }],
      state: { engine: 'e1', voice: 'v1', rate: 100, use: {} },
      lines: 1,
      timings: null
    }))
    const reqs = recordRequests('/api/voiceover/build')
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    expect(await screen.findByText('Speak the script')).toBeInTheDocument()

    // Change speed
    const rateInput = screen.getByLabelText(/Speed/i)
    await user.clear(rateInput)
    await user.type(rateInput, '120')

    // Change voice
    const voiceSelect = screen.getByLabelText(/Voice/i)
    await user.selectOptions(voiceSelect, 'v2')

    // Building is triggered by voice change
    await waitFor(() => expect(reqs).toHaveLength(1))
    expect(reqs[0].body).toEqual({ folder: '/data', engine: 'e1', voice: 'v2', rate: 120 })

    await user.click(screen.getByRole('button', { name: 'Speak the script' }))
    await waitFor(() => expect(reqs).toHaveLength(2))
  })

  it('displays script lines, timings, and allows switching to recorded take', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      lines: 2,
      timings: {
        script: 'abc',
        engine: 'e1',
        voice: 'v1',
        rate: 100,
        film_length_s: 60,
        measured_wpm: 150,
        over: [1],
        sped: [],
        lines: [
          { seg: 1, text: 'Too long line.', source: 'synth', has_recording: true, film_start_s: 0, window_s: 10, room_s: 2, natural_s: 4, played_s: 2, overrun_s: 2, tempo: 1, fit: 'over', synth_s: 4 },
          { seg: 2, text: 'Okay line.', source: 'recorded', has_recording: true, film_start_s: 10, window_s: 10, room_s: 10, natural_s: 2, played_s: 2, overrun_s: 0, tempo: 1, fit: 'ok', synth_s: 2 },
        ]
      }
    }))
    const useReqs = recordRequests('/api/voiceover/use')
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    expect(await screen.findByText(/measured pace 150 words per minute/)).toBeInTheDocument()
    expect(screen.getByText('1 line(s) too long')).toBeInTheDocument()

    expect(screen.getByText('Too long line.')).toBeInTheDocument()
    expect(screen.getByText('4.0s in 2.0s (+2.0)')).toBeInTheDocument()

    // Test playing recorded line
    const playRecBtn = screen.getAllByTitle(/Play your recording/)[1]
    await user.click(playRecBtn)

    // Test switching to synthetic via double click
    const synthBtn = screen.getAllByTitle(/Play the synthetic line/)[1] // second line
    await user.dblClick(synthBtn)

    await waitFor(() => expect(useReqs).toHaveLength(1))
    expect(useReqs[0].body).toEqual({ folder: '/data', seg: 2, use: 'synth' })
  })

  it('can delete a recording', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      lines: 1,
      timings: {
        script: 'abc', engine: 'e1', voice: 'v1', rate: 100, film_length_s: 60, measured_wpm: 150, over: [], sped: [],
        lines: [
          { seg: 1, text: 'Test', source: 'recorded', has_recording: true, film_start_s: 0, window_s: 10, room_s: 10, natural_s: 2, played_s: 2, overrun_s: 0, tempo: 1, fit: 'ok', synth_s: 2 }
        ]
      }
    }))
    const reqs = recordRequests('/api/voiceover/record')
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const delBtn = await screen.findByTitle('Remove your recording')
    await user.click(delBtn)

    await waitFor(() => expect(reqs).toHaveLength(1))
    // delete request query has folder and seg (msw matches on pathname for recordRequests, so body is empty, we just verify the call was made)
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({ lines: 1, timings: { script: 'a', engine: 'e1', voice: 'v1', rate: 100, film_length_s: 10, measured_wpm: 120, over: [], sped: [], lines: [] } }))
    const { container } = setup(<VoiceoverPanel folder="/data" />)
    await screen.findByText('Speak again')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('can record your own take and upload it', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      lines: 1,
      timings: {
        script: 'abc', engine: 'e1', voice: 'v1', rate: 100, film_length_s: 60, measured_wpm: 150, over: [], sped: [],
        lines: [
          { seg: 1, text: 'Test', source: 'synth', has_recording: false, film_start_s: 0, window_s: 10, room_s: 10, natural_s: 2, played_s: 2, overrun_s: 0, tempo: 1, fit: 'ok', synth_s: 2 }
        ]
      }
    }))
    const reqs = recordRequests('/api/voiceover/record')
    const buildReqs = recordRequests('/api/voiceover/build')

    // Mock getUserMedia
    const trackStop = vi.fn()
    const getTracks = vi.fn(() => [{ stop: trackStop }])
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks }) },
      configurable: true
    })

    // Mock MediaRecorder
    const start = vi.fn()
    const stop = vi.fn()
    let ondataavailable: ((e: any) => void) | null = null
    let onstop: (() => void) | null = null
    class MockMediaRecorder {
      mimeType = 'audio/webm'
      start = start
      stop = () => { stop(); if (onstop) onstop() }
      set ondataavailable(cb: any) { ondataavailable = cb }
      set onstop(cb: any) { onstop = cb }
    }
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)

    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const recordBtn = await screen.findByRole('button', { name: '● record' })
    await user.click(recordBtn)

    expect(start).toHaveBeenCalled()

    const stopBtn = await screen.findByRole('button', { name: '■ stop' })

    // Simulate some data
    if (ondataavailable) (ondataavailable as any)({ data: new Blob(['data']) })

    await user.click(stopBtn)

    expect(trackStop).toHaveBeenCalled()
    await waitFor(() => expect(reqs).toHaveLength(1))
    await waitFor(() => expect(buildReqs).toHaveLength(1))

    // Check stop from media recorder stop call directly to cover line 62 completely
    const startRec2Btn = await screen.findByRole('button', { name: '● record' })
    await user.click(startRec2Btn)

    const stop2Btn = await screen.findByRole('button', { name: '■ stop' })
    expect(stop2Btn).toBeInTheDocument()

    // Simulate failing api.recordVoiceover for coverage of line 62
    mockError('/api/voiceover/record', 500, 'boom', 'post')
    await user.click(stop2Btn)
    expect(await screen.findByText('boom')).toBeInTheDocument()

    vi.unstubAllGlobals()
  })

  it('handles microphone permission denied', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      lines: 1,
      timings: {
        script: 'abc', engine: 'e1', voice: 'v1', rate: 100, film_length_s: 60, measured_wpm: 150, over: [], sped: [],
        lines: [
          { seg: 1, text: 'Test', source: 'synth', has_recording: false, film_start_s: 0, window_s: 10, room_s: 10, natural_s: 2, played_s: 2, overrun_s: 0, tempo: 1, fit: 'ok', synth_s: 2 }
        ]
      }
    }))

    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true
    })

    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const recordBtn = await screen.findByRole('button', { name: '● record' })
    await user.click(recordBtn)

    expect(await screen.findByText('The browser could not use a microphone (it needs permission, and https or localhost).')).toBeInTheDocument()
  })

  it('displays the cached voices and can play them', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      engines: [{ id: 'e1', label: 'E1', voices: [{ name: 'v1', lang: 'en' }, { name: 'v2', lang: 'en' }] }],
      state: { engine: 'e1', voice: 'v1', rate: 100, use: {} },
      cached: [
        { key: 'k1', engine: 'e1', voice: 'v2', rate: 100, active: false, measured_wpm: 150, over: 0, sped: 0 },
        { key: 'k2', engine: 'e1', voice: 'v1', rate: 100, active: true, measured_wpm: 150, over: 0, sped: 0 }
      ],
      lines: 1,
      timings: {
        script: 'abc', engine: 'e1', voice: 'v1', rate: 100, film_length_s: 60, measured_wpm: 150, over: [], sped: [], lines: []
      }
    }))
    const { user } = setup(<VoiceoverPanel folder="/data" />)

    const playWholeTrack = await screen.findByRole('button', { name: '▶ Whole track' })
    await user.click(playWholeTrack)

    const playCached = await screen.findByRole('button', { name: '▶ v2' })
    await user.click(playCached)

    const useCached = screen.getByRole('button', { name: 'use' })
    const buildReqs = recordRequests('/api/voiceover/build')
    await user.click(useCached)

    await waitFor(() => expect(buildReqs).toHaveLength(1))
    expect(buildReqs[0].body).toEqual({ folder: '/data', engine: 'e1', voice: 'v2', rate: 100 })

    expect(screen.getByText('in use')).toBeInTheDocument()
  })

  it('displays building progress state and handles build error', async () => {
    mockGet('/api/voiceover', () => makeVoiceoverState({
      building: true,
      progress: { done: 3, total: 10 },
      lines: 5
    }))
    const { unmount } = setup(<VoiceoverPanel folder="/data" />)

    expect(await screen.findByText('Speaking 3/10')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Speaking 3/10' })).toBeDisabled()
    unmount()

    mockGet('/api/voiceover', () => makeVoiceoverState({
      lines: 1,
      error: 'Failed to synthesize'
    }))
    setup(<VoiceoverPanel folder="/data" />)
    expect(await screen.findByText('Failed to synthesize')).toBeInTheDocument()
  })
})
