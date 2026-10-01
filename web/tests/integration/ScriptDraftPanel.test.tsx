import { describe, expect, it } from 'vitest'
import ScriptDraftPanel from '../../src/components/ScriptDraftPanel'
import { screen, setup, waitFor, within } from '../utils/render'
import { makeScript2State, makeScriptDraft, makeSeg } from '../utils/factories'
import { mockGet, mockError, recordRequests } from '../utils/api'

const CLIP = 'CAM_20260222130830_0023_D'
const word = (i: number, w: string, m?: 'must' | 'never') => ({ i, w, t0: i, t1: i + 0.4, ...(m ? { m } : {}) })
const transcript = (m1?: 'must' | 'never') => ({ segments: [makeSeg({ si: 0, clip: CLIP, text: 'we are fine', words: [word(0, 'we', m1), word(1, 'are'), word(2, 'fine')] }), makeSeg({ si: 1, clip: CLIP, text: 'not used', words: [word(0, 'not'), word(1, 'used')] })] })

describe('ScriptDraftPanel', () => {
  it('offers to write a first draft when there is none', async () => {
    const seen = recordRequests('/api/script2/generate')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/No draft yet/)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/length/), '200'); await user.click(screen.getByLabelText(/ignore the music/))
    await user.click(screen.getByRole('button', { name: 'Write a draft' }))
    await waitFor(() => expect(seen).toHaveLength(1))
    expect(seen[0].body).toEqual({ folder: '/data', revise: false, target_s: 200, auto: true })
  })

  it('needs the Gemini key before it can write', async () => {
    mockGet('/api/script2', makeScript2State({ key_configured: false }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/No Gemini API key/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Write a draft' })).toBeDisabled()
  })

  it('shows the draft: title, totals, narration, the runner\'s own words, and b-roll', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), used: ['0023.00'] })); mockGet('/api/transcript', transcript())
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText('A Film')).toBeInTheDocument()
    expect(screen.getByText(/61.2 s of 60 s \(music\)/)).toBeInTheDocument()
    expect(screen.getByText('It is Sunday afternoon.')).toHaveAttribute('title', 'based on: Sun 22 Feb 14:04')
    expect(screen.getByText('a foggy trail')).toBeInTheDocument()
    const w = await screen.findByText('are'); expect(w).toHaveAttribute('data-state', 'used')                 // the runner's words come from the transcript, yellow because the draft plays them
    expect(screen.queryByText('not')).not.toBeInTheDocument()                                                  // only the words of the lines the draft plays
    expect(screen.getByRole('button', { name: 'Revise this draft' })).toBeEnabled()
  })

  it('shows the user\'s marks on the words and lets them mark more by selecting', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), used: ['0023.00'] })); mockGet('/api/transcript', transcript('must'))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText('we')).toHaveAttribute('data-state', 'must')
  })

  it('revises the current draft', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft() })); const seen = recordRequests('/api/script2/generate')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Revise this draft' }))
    await waitFor(() => expect(seen).toHaveLength(1)); expect((seen[0].body as { revise: boolean }).revise).toBe(true)
  })

  it('flags items that are new since the previous draft', async () => {
    const prev = makeScriptDraft({ items: makeScriptDraft().items.slice(0, 2) })
    mockGet('/api/script2', req => new URL(req.url).searchParams.get('name') === 'draft-1.json' ? makeScript2State({ draft: prev }) : makeScript2State({ draft: makeScriptDraft({ revised: true, draft_of: 'draft-1.json' }), drafts: ['draft-1.json', 'draft-2.json'] }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/1 new, 0 removed/)).toBeInTheDocument(); expect(screen.getByText('new')).toBeInTheDocument()
  })

  it('puts a warning mark on the item it is about', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft({ warnings: ['item 1: the number 300 is not in the material'] }) }))
    setup(<ScriptDraftPanel folder="/data" />)
    const mark = await screen.findByLabelText(/check: the number 300 is not in the material/); expect(mark).toHaveAttribute('title', 'the number 300 is not in the material')
  })

  it('lists the clips left out', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft({ skipped: [{ clip: '0001', why: 'indoors, no speech' }] }) }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText('1 clip(s) left out')).toBeInTheDocument(); expect(screen.getByText(/indoors, no speech/)).toBeInTheDocument()
  })

  it('shows progress while a draft is being written and an error when it failed', async () => {
    mockGet('/api/script2', makeScript2State({ running: true, log: ['attempt 0: 112 s'] }))
    const { unmount } = setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText('attempt 0: 112 s')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'writing…' })).toBeDisabled(); unmount()
    mockGet('/api/script2', makeScript2State({ last_exit: 1, log: ['Traceback: no key'] })); setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/The last attempt failed: Traceback: no key/)).toBeInTheDocument()
  })

  it('says so when a draft cannot be started', async () => {
    mockError('/api/script2/generate', 500, 'boom', 'post')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Write a draft' }))
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('has the three-line summary inside a labelled section', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft() })); setup(<ScriptDraftPanel folder="/data" />)
    await screen.findByText('A Film'); const h = screen.getByText('Film script'); expect(within(h.closest('section')!).getByText('clip 0023')).toBeInTheDocument()
  })
})
