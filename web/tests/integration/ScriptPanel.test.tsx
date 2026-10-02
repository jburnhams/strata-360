import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setup, screen } from '../utils/render'
import ScriptPanel from '../../src/components/ScriptPanel'
import { mockGet, mockPost, recordRequests } from '../utils/api'
import { makeScriptState, makeScriptDoc, makeScriptLine } from '../utils/factories'

describe('ScriptPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  it('renders without a key configured', async () => {
    mockGet('/api/script', () => makeScriptState({ key_configured: false, providers: { vertex: { models: ['gemini-1.5-pro'], default: 'gemini-1.5-pro', configured: false } }, llm: { provider: 'vertex', model: 'gemini-1.5-pro' } }))
    const { user } = setup(<ScriptPanel folder="/data" onOpen={() => {}} />)

    const el = await screen.findByText(/Paste its API key/)
    expect(el).toBeInTheDocument()

    const input = await screen.findByPlaceholderText('AQ.…')
    await user.type(input, 'my-key')

    const saveBtn = screen.getByRole('button', { name: 'Save key' })
    const rec = recordRequests('/api/llm/key')
    await user.click(saveBtn)

    expect(rec).toHaveLength(1)
    expect(rec[0].body).toEqual({ key: 'my-key', provider: 'vertex' })
  })

  it('renders configured state and generates script', async () => {
    mockGet('/api/script', () => makeScriptState({ key_configured: true, llm: { provider: 'vertex', model: 'gemini-1.5-pro' } }))
    const { user } = setup(<ScriptPanel folder="/data" onOpen={() => {}} />)

    expect(await screen.findByRole('button', { name: 'Write the script' })).toBeInTheDocument()

    const lengthInput = screen.getByLabelText(/Film length/i)
    await user.clear(lengthInput)
    await user.type(lengthInput, '120')

    const rec = recordRequests('/api/script/generate')
    const generateBtn = screen.getByRole('button', { name: 'Write the script' })
    await user.click(generateBtn)

    expect(rec).toHaveLength(1)
    expect(rec[0].body).toEqual({ folder: '/data', length: 120, provider: 'vertex', model: 'gemini-1.5-pro' })
  })

  it('renders ScriptDoc and saves edited line', async () => {
    mockGet('/api/script', () => makeScriptState({
      key_configured: true,
      latest: makeScriptDoc({ lines: [makeScriptLine({ seg: 1, text: 'Hello' })] })
    }))
    const { user } = setup(<ScriptPanel folder="/data" onOpen={() => {}} />)

    expect(await screen.findByText(/1 words, about 1 s of speech/)).toBeInTheDocument()

    const textbox = screen.getByTitle('edit the line: it is saved when you click away, and the voice-over is made again')
    expect(textbox).toHaveValue('Hello')

    await user.clear(textbox)
    await user.type(textbox, 'New Text')

    const rec = recordRequests('/api/script/edit')
    await user.tab()

    expect(rec).toHaveLength(1)
    expect(rec[0].body).toEqual({ folder: '/data', texts: { '1': 'New Text' } })
  })
})
