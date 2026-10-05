import { describe, it, expect, vi } from 'vitest'
import { axe } from 'vitest-axe'
import userEvent from '@testing-library/user-event'
import { setup, screen, waitFor } from '../utils/render'
import { mockGet, mockPost, recordRequests, mockPending, mockError } from '../utils/api'
import { makeScriptState } from '../utils/factories'
import ScriptPanel from '../../src/components/ScriptPanel'

describe('ScriptPanel', () => {
  it('renders a skeleton while loading', () => {
    mockPending('/api/script')
    setup(<ScriptPanel folder="/data" onOpen={vi.fn()} />)
    expect(screen.getByText('Voice-over script')).toBeInTheDocument()
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
  })

  it('prompts for an API key if not configured, and saves it', async () => {
    mockGet('/api/script', () => makeScriptState({ key_configured: false, llm: { provider: 'anthropic', model: 'claude-3' }, providers: { anthropic: { models: ['claude-3'], default: 'claude-3', configured: false } } }))
    const reqs = recordRequests('/api/llm/key')
    const { user } = setup(<ScriptPanel folder="/data" onOpen={vi.fn()} />)

    expect(await screen.findByText(/The script is written by Claude/)).toBeInTheDocument()

    const input = screen.getByPlaceholderText('sk-ant-…')
    await user.type(input, 'my-test-key')

    await user.click(screen.getByRole('button', { name: 'Save key' }))

    await waitFor(() => expect(reqs).toHaveLength(1))
    expect(reqs[0].body).toEqual({ key: 'my-test-key', provider: 'anthropic' })
  })

  it('shows error if saving key fails', async () => {
    mockGet('/api/script', () => makeScriptState({ key_configured: false, llm: { provider: 'anthropic', model: 'claude-3' }, providers: { anthropic: { models: ['claude-3'], default: 'claude-3', configured: false } } }))
    mockError('/api/llm/key', 400, 'Invalid key format', 'post')
    const { user } = setup(<ScriptPanel folder="/data" onOpen={vi.fn()} />)

    await user.type(await screen.findByPlaceholderText('sk-ant-…'), 'bad')
    await user.click(screen.getByRole('button', { name: 'Save key' }))
    expect(await screen.findByText('Invalid key format')).toBeInTheDocument()
  })

  it('generates a new script', async () => {
    mockGet('/api/script', () => makeScriptState({ key_configured: true, latest: null }))
    const reqs = recordRequests('/api/script/generate')
    const { user } = setup(<ScriptPanel folder="/data" onOpen={vi.fn()} />)

    expect(await screen.findByText('No script yet. It plans a film of that length from your usable moments, then writes narration for each segment.')).toBeInTheDocument()

    const lengthInput = screen.getByLabelText(/Film length/i)
    await user.clear(lengthInput)
    await user.type(lengthInput, '120')

    const styleInput = screen.getByLabelText(/Style/i)
    await user.type(styleInput, 'energetic')

    await user.click(screen.getByRole('button', { name: 'Write the script' }))

    await waitFor(() => expect(reqs).toHaveLength(1))
    expect(reqs[0].body).toEqual({ folder: '/data', length: 120, style: 'energetic', provider: 'anthropic', model: 'claude-3' })
  })

  it('displays an existing script and allows editing lines', async () => {
    mockGet('/api/script', () => makeScriptState({
      key_configured: true,
      latest: {
        file: 'script.json',
        title: 'A Good Film',
        target_s: 60,
        wpm: 150,
        total_words: 40,
        total_speak_s: 16,
        remaining_problems: [{ seg: 2, problem: 'too short' }],
        lines: [
          { seg: 1, film_start_s: 0, seconds: 10, clip: 'CAM_1', text: 'This is the start.', words: 4, est_speak_s: 2, budget_words: 10 },
          { seg: 2, film_start_s: 10, seconds: 5, clip: 'CAM_2', text: '', words: 0, est_speak_s: 0, budget_words: 0, says: ['hello'] },
        ]
      }
    }))
    const reqs = recordRequests('/api/script/edit')
    const onOpen = vi.fn()
    const { user } = setup(<ScriptPanel folder="/data" onOpen={onOpen} />)

    expect(await screen.findByText('A Good Film')).toBeInTheDocument()
    expect(screen.getByText(/40 words, about 16 s of speech/)).toBeInTheDocument()
    expect(screen.getByText('Still to fix: segment 2: too short')).toBeInTheDocument()

    // Test clicking a clip opens it
    // short(CAM_1) slices the last 9 characters, but since 'CAM_1' is 5 chars, slice(-9) will return '1'
    await user.click(screen.getByRole('button', { name: '1' }))
    expect(onOpen).toHaveBeenCalledWith('CAM_1')

    // Test editing a line
    const textarea = screen.getByDisplayValue('This is the start.')
    await user.clear(textarea)
    await user.type(textarea, 'A new beginning.')
    await user.tab() // blur triggers save

    await waitFor(() => expect(reqs).toHaveLength(1))
    expect(reqs[0].body).toEqual({ folder: '/data', texts: { '1': 'A new beginning.' } })
    expect(await screen.findByText('saved: the voice-over is being made again')).toBeInTheDocument()

    // Check says fallback
    expect(await screen.findByText(/💬 “hello”/)).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    mockGet('/api/script', () => makeScriptState({ key_configured: true, latest: null }))
    const { container } = setup(<ScriptPanel folder="/data" onOpen={vi.fn()} />)
    await screen.findByText('Write the script')
    expect(await axe(container)).toHaveNoViolations()
  })
})
