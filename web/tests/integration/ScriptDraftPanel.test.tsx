import { describe, expect, it } from 'vitest'
import { act } from '@testing-library/react'
import ScriptDraftPanel from '../../src/components/ScriptDraftPanel'
import { screen, setup, waitFor, within } from '../utils/render'
import { makeScript2State, makeScriptDraft, makeSeg } from '../utils/factories'
import { mockGet, mockError, recordRequests } from '../utils/api'

const CLIP = 'CAM_20260222130830_0023_D'
const word = (i: number, w: string, m?: 'must' | 'never') => ({ i, w, t0: i, t1: i + 0.4, ...(m ? { m } : {}) })
const transcript = (m1?: 'must' | 'never') => ({ segments: [makeSeg({ si: 0, clip: CLIP, text: 'we are fine', words: [word(0, 'we', m1), word(1, 'are'), word(2, 'fine')] }), makeSeg({ si: 1, clip: CLIP, text: 'not used', words: [word(0, 'not'), word(1, 'used')] })] })

describe('ScriptDraftPanel', () => {
  it('still renders a draft whose narration basis is one string (not a list)', async () => {
    mockGet('/api/script2', makeScript2State({ drafts: ['d1.json'], draft: makeScriptDraft({ items: [
      { type: 'vo', clip: '0023', text: 'It is Sunday afternoon.', basis: 'Sun 22 Feb 14:04' as unknown as string[], seconds: 4 }] }) }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect((await screen.findByText(/It is Sunday afternoon/)).closest('[data-vo]')).toHaveAttribute('title', 'based on: Sun 22 Feb 14:04')
  })

  it('shows a gap item with its kind, length, reason and anchor', async () => {
    mockGet('/api/script2', makeScript2State({ drafts: ['d1.json'], draft: makeScriptDraft({ items: [
      { type: 'gap', clip: 'G03', kind: 'flyover', seconds: 14, why: 'the long night climb', anchor: { film_s: 100, why: 'the chorus' } },
      { type: 'gap', clip: 'G04', kind: 'map', seconds: 8, why: 'a quiet hour' },
      { type: 'clip', clip: '0023', from: '0023.00', to: '0023.01', view: 'close' }] }) }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/3D flyover, 14 s: the long night climb/)).toBeInTheDocument()
    expect(screen.getByText(/2D map, 8 s: a quiet hour/)).toBeInTheDocument(); expect(screen.getByText('anchored at 100 s')).toBeInTheDocument(); expect(screen.getAllByText('gap')).toHaveLength(2); expect(screen.getByText('close view of you')).toBeInTheDocument()
  })

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
    expect(screen.getByText('It is Sunday afternoon.').closest('[data-vo]')).toHaveAttribute('title', 'based on: Sun 22 Feb 14:04')
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

async function selectText(el: HTMLElement) {
  const r = document.createRange(); r.selectNodeContents(el); const s = window.getSelection()!; s.removeAllRanges(); s.addRange(r)
  await act(async () => { document.dispatchEvent(new Event('selectionchange')) })
}

describe('ScriptDraftPanel narration pins', () => {
  const withDraft = (pins = {}) => mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), pins }))

  it('shows pinned wording in green and never-say wording in red', async () => {
    withDraft({ vo: [{ id: 'v1', text: 'Sunday afternoon', mode: 'clip', clip: '0023' }], vo_never: ['It is'] })
    setup(<ScriptDraftPanel folder="/data" />)
    await screen.findByText('A Film'); const green = screen.getAllByText('Sunday afternoon')[0]; expect(green.className).toContain('emerald'); expect(screen.getAllByText('It is')[0].className).toContain('red')
  })

  it('pins selected narration as "say exactly this" in its clip', async () => {
    withDraft(); const seen = recordRequests('/api/script2/pins')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await selectText(await screen.findByText('It is Sunday afternoon.'))
    expect(await screen.findByRole('toolbar', { name: 'Mark the selected narration' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Say exactly this' }))
    await waitFor(() => expect(seen).toHaveLength(1))
    expect(seen[0].body).toEqual({ folder: '/data', vo: [{ id: 'v1', text: 'It is Sunday afternoon.', mode: 'clip', clip: '0023' }] })
  })

  it('bans selected narration with "never say"', async () => {
    withDraft(); const seen = recordRequests('/api/script2/pins')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await selectText(await screen.findByText('It is Sunday afternoon.')); await user.click(await screen.findByRole('button', { name: 'Never say' }))
    await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toEqual({ folder: '/data', vo_never: ['It is Sunday afternoon.'] })
  })

  it('keeps an edited narration word for word: it becomes a pin, and shows the new wording at once', async () => {
    withDraft(); const seen = recordRequests('/api/script2/pins')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Edit narration 1' }))
    const box = screen.getByLabelText('Narration 1'); await user.clear(box); await user.type(box, 'Sunday, two in the afternoon.')
    await user.click(screen.getByRole('button', { name: /save/ }))
    await waitFor(() => expect(seen).toHaveLength(1))
    expect(seen[0].body).toEqual({ folder: '/data', vo: [{ id: 'v1', text: 'Sunday, two in the afternoon.', mode: 'clip', clip: '0023' }] })
    expect(await screen.findByText('Sunday, two in the afternoon.')).toBeInTheDocument()
  })

  it('does nothing when an edit is cancelled or unchanged', async () => {
    withDraft(); const seen = recordRequests('/api/script2/pins')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await user.click(await screen.findByRole('button', { name: 'Edit narration 1' })); await user.click(screen.getByRole('button', { name: 'cancel' }))
    await user.click(screen.getByRole('button', { name: 'Edit narration 1' })); await user.click(screen.getByRole('button', { name: /save/ }))
    expect(seen).toHaveLength(0); expect(screen.getByText('It is Sunday afternoon.')).toBeInTheDocument()
  })

  it('lists the pins, loosens one to "anywhere" and removes another', async () => {
    withDraft({ vo: [{ id: 'v1', text: 'Keep this', mode: 'clip', clip: '0023' }, { id: 'v2', text: 'And this', mode: 'ordered' }], vo_never: ['best day'] }); const seen = recordRequests('/api/script2/pins')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await user.click(await screen.findByText(/Your narration pins \(3\)/))
    await user.selectOptions(screen.getByLabelText('Where to say v1'), 'anywhere')
    await waitFor(() => expect(seen).toHaveLength(1)); expect((seen[0].body as { vo: unknown[] }).vo[0]).toEqual({ id: 'v1', text: 'Keep this', mode: 'anywhere' })
    await user.click(screen.getByRole('button', { name: 'Remove never-say best day' }))
    await waitFor(() => expect(seen).toHaveLength(2)); expect((seen[1].body as { vo_never: string[] }).vo_never).toEqual([])
  })

  it('says so when the pins cannot be saved', async () => {
    withDraft({ vo: [{ id: 'v1', text: 'x', mode: 'anywhere' }] }); mockError('/api/script2/pins', 400, 'bad pins', 'post')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    await user.click(await screen.findByText(/Your narration pins/)); await user.click(screen.getByRole('button', { name: 'Remove pin v1' }))
    expect(await screen.findByText('bad pins')).toBeInTheDocument()
  })
})

describe('ScriptDraftPanel film plan', () => {
  const plan = (o = {}) => ({ source: 'script' as const, script: 'draft-2.json', windows: 35, length_s: 259.8, warnings: [] as string[], generated_at: '2026-10-03T08:00:00Z', ...o })

  it('makes the film from the draft in the background', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), drafts: ['draft-2.json'] })); const seen = recordRequests('/api/script2/plan')
    const { user } = setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/still the beat planner/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Make the film from this draft' }))
    await waitFor(() => expect(seen).toHaveLength(1)); expect(seen[0].body).toMatchObject({ folder: '/data' })
  })

  it('says which draft the film plan comes from and warns when it is an older one', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), drafts: ['draft-1.json', 'draft-2.json'], plan: plan({ script: 'draft-1.json' }) }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/35 windows, 259.8 s, from an older draft/)).toBeInTheDocument()
  })

  it('says the plan is from this draft, and lists the planner\'s warnings', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), drafts: ['draft-2.json'], plan: plan({ warnings: ['clip 0025: not enough free footage for 4.0 s of picture (reused)'] }) }))
    setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/Film plan: 35 windows, 259.8 s, from this draft/)).toBeInTheDocument(); expect(screen.getByText(/clip 0025: not enough free footage/)).toBeInTheDocument()
  })

  it('shows progress and failure of the planning', async () => {
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), plan_running: true, plan_log: ['speaking line 3 of 6'] }))
    const { unmount } = setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText('speaking line 3 of 6')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'planning…' })).toBeDisabled(); unmount()
    mockGet('/api/script2', makeScript2State({ draft: makeScriptDraft(), plan_exit: 1, plan_log: ['no candidates yet'] })); setup(<ScriptDraftPanel folder="/data" />)
    expect(await screen.findByText(/Planning failed: no candidates yet/)).toBeInTheDocument()
  })
})
