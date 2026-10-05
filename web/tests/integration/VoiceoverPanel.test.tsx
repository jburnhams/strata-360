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
})
