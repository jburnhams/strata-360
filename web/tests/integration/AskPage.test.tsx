import { describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import AskPage, { inline } from '../../src/components/AskPage'
import type { AgentAnswer, AgentPending, AgentStatus, AgentUndoState } from '../../src/api'
import { mockError, mockGet, mockNetworkError, mockPending, mockPost, recordRequests } from '../utils/api'
import { act, screen, setup, within } from '../utils/render'

const status = (o: Partial<AgentStatus> = {}): AgentStatus => ({ configured: true, model: 'nvidia/nemotron-3-super-120b-a12b', vision_model: 'meta/llama-3.2-11b-vision-instruct', read_only: true, available: true, ...o })
const answer = (o: Partial<AgentAnswer> = {}): AgentAnswer => ({ answer: 'There are 3 clips.', steps: [], images: [], model: 'm', vision: false, seconds: 1, ...o })
const pend = (o: Partial<AgentPending> = {}): AgentPending => ({ id: 'p1', action: 'final.render', summary: 'start the final film render (hours of work, large files)', why: 'a long, heavy render', args: {}, ...o })
const undoState = (o: Partial<AgentUndoState> = {}): AgentUndoState => ({ available: true, restore_point: 'meta-1.tar.gz', since: 1_800_000_000, changes: 1, sessions: 1, ...o })
const props = { folder: '/f', clipIds: ['CAM_1', 'CAM_2'], onOpenClip: vi.fn() }
const ask = async (user: ReturnType<typeof setup>['user'], q: string) => { await user.type(await screen.findByLabelText('Your question'), q); await user.click(screen.getByRole('button', { name: 'Ask' })) }

describe('AskPage', () => {
  it('shows a skeleton until the server says whether the assistant is set up', () => {
    mockPending('/api/agent'); setup(<AskPage {...props} />)
    expect(screen.queryByLabelText('Your question')).not.toBeInTheDocument()
  })

  it('offers example questions when ready, and an example asks itself', async () => {
    mockGet('/api/agent', status()); const seen = recordRequests('/api/agent/chat'); mockPost('/api/agent/chat', answer())
    const { user } = setup(<AskPage {...props} />)
    await user.click(await screen.findByRole('button', { name: /How many clips are there/ }))
    expect(await screen.findByText('There are 3 clips.')).toBeInTheDocument()
    expect(seen[0].body).toMatchObject({ folder: '/f', vision: false, messages: [{ role: 'user', content: expect.stringContaining('How many clips') }] })
  })

  it.each([
    ['no key', status({ configured: false }), /NVIDIA_API_KEY/],
    ['no mcp package', status({ available: false }), /pip install mcp/],
  ])('explains what is missing and disables the box: %s', async (_n, s, words) => {
    mockGet('/api/agent', s); setup(<AskPage {...props} />)
    expect(await screen.findByRole('status')).toHaveTextContent(words)
    expect(screen.getByLabelText('Your question')).toBeDisabled(); expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
  })

  it('says so when the server cannot tell', async () => {
    mockError('/api/agent', 500, 'boom'); setup(<AskPage {...props} />)
    expect(await screen.findByRole('status')).toHaveTextContent(/did not say/); expect(screen.getByLabelText('Your question')).toBeDisabled()
  })

  it('asks a question, shows it and the answer, and sends the whole conversation next time', async () => {
    mockGet('/api/agent', status()); const seen = recordRequests('/api/agent/chat'); mockPost('/api/agent/chat', answer())
    const { user } = setup(<AskPage {...props} />)
    await ask(user, 'How many clips?'); expect(await screen.findByText('How many clips?')).toBeInTheDocument(); expect(await screen.findByText('There are 3 clips.')).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toHaveValue('')
    await ask(user, 'And the longest?'); await screen.findAllByText('There are 3 clips.')
    expect(seen[1].body).toMatchObject({ messages: [{ role: 'user', content: 'How many clips?' }, { role: 'assistant', content: 'There are 3 clips.' }, { role: 'user', content: 'And the longest?' }] })
  })

  it('sends on Enter but not on Shift+Enter, and not an empty question', async () => {
    mockGet('/api/agent', status()); const seen = recordRequests('/api/agent/chat'); mockPost('/api/agent/chat', answer())
    const { user } = setup(<AskPage {...props} />)
    const box = await screen.findByLabelText('Your question'); expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    await user.type(box, 'one{Shift>}{Enter}{/Shift}two'); expect(seen).toHaveLength(0); expect(box).toHaveValue('one\ntwo')
    await user.type(box, '{Enter}'); expect(await screen.findByText('There are 3 clips.')).toBeInTheDocument(); expect(seen).toHaveLength(1)
  })

  it('shows that it is looking, and does not take a second question meanwhile', async () => {
    mockGet('/api/agent', status()); mockPending('/api/agent/chat', 'post')
    const { user } = setup(<AskPage {...props} />); await ask(user, 'q')
    expect(await screen.findByText('Looking…')).toBeInTheDocument(); await user.type(screen.getByLabelText('Your question'), 'again'); expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
  })

  it('shows a server error in the conversation and leaves it out of the next request', async () => {
    mockGet('/api/agent', status()); mockError('/api/agent/chat', 503, 'the model service could not be reached', 'post')
    const { user } = setup(<AskPage {...props} />); await ask(user, 'first')
    expect(await screen.findByText('the model service could not be reached')).toBeInTheDocument()
    const seen = recordRequests('/api/agent/chat'); mockPost('/api/agent/chat', answer({ answer: 'Back again.' })); await ask(user, 'second')
    expect(await screen.findByText('Back again.')).toBeInTheDocument(); expect(seen[0].body).toMatchObject({ messages: [{ role: 'user', content: 'first' }, { role: 'user', content: 'second' }] })
  })

  it('shows a dropped connection as an error too', async () => {
    mockGet('/api/agent', status()); mockNetworkError('/api/agent/chat', 'post'); const { user } = setup(<AskPage {...props} />); await ask(user, 'q')
    expect(await screen.findByText(/fetch failed|failed to fetch/i)).toBeInTheDocument()
  })

  it('lists what the assistant looked at, with the arguments and the time', async () => {
    mockGet('/api/agent', status()); mockPost('/api/agent/chat', answer({ steps: [{ tool: 'clips', args: { sort: 'longest' }, seconds: 0.4, chars: 90, error: null }, { tool: 'clip', args: { clip: 'x' }, seconds: 0.1, chars: 9, error: 'no such clip' }] }))
    const { user } = setup(<AskPage {...props} />); await ask(user, 'q')
    expect(await screen.findByText(/Looked at 2 things: clips, clip/)).toBeInTheDocument()
    await user.click(screen.getByText(/Looked at 2 things/)); expect(screen.getByText('clips(sort="longest") · 0.4 s')).toBeInTheDocument(); expect(screen.getByText(/clip\(clip="x"\) · 0.1 s · no such clip/)).toBeInTheDocument()
  })

  it('shows the pictures the assistant fetched, each opening full size', async () => {
    mockGet('/api/agent', status()); mockPost('/api/agent/chat', answer({ images: [{ url: '/api/clip/frame?folder=%2Ff&clip=CAM_1&t=4', caption: 'CAM_1 at 4 s' }] }))
    const { user } = setup(<AskPage {...props} />); await ask(user, 'show me')
    const img = await screen.findByRole('img', { name: 'CAM_1 at 4 s' }); expect(img).toHaveAttribute('src', '/api/clip/frame?folder=%2Ff&clip=CAM_1&t=4')
    expect(screen.getByRole('link', { name: 'CAM_1 at 4 s' })).toHaveAttribute('target', '_blank'); expect(screen.getByText('CAM_1 at 4 s', { selector: 'figcaption' })).toBeInTheDocument()
  })

  it('lets the model see the pictures only when the box is ticked', async () => {
    mockGet('/api/agent', status()); const seen = recordRequests('/api/agent/chat'); mockPost('/api/agent/chat', answer())
    const { user } = setup(<AskPage {...props} />)
    const box = await screen.findByRole('checkbox', { name: /Let the model see the pictures.*llama-3.2-11b-vision/ }); expect(box).not.toBeChecked()
    await ask(user, 'a'); await screen.findByText('There are 3 clips.'); await user.click(box); await ask(user, 'b'); await vi.waitFor(() => expect(seen).toHaveLength(2))
    expect(seen.map(s => (s.body as { vision: boolean }).vision)).toEqual([false, true])
  })

  it('turns a clip id in an answer into a button that opens the clip, and formats bold and code', async () => {
    const onOpenClip = vi.fn(); mockGet('/api/agent', status()); mockPost('/api/agent/chat', answer({ answer: 'The longest is **CAM_2** at `4.5 s`; also CAM_1.' }))
    const { user } = setup(<AskPage {...props} onOpenClip={onOpenClip} />); await ask(user, 'q')
    await user.click(await screen.findByRole('button', { name: 'CAM_2' })); expect(onOpenClip).toHaveBeenCalledWith('CAM_2')
    await user.click(screen.getByRole('button', { name: 'CAM_1' })); expect(onOpenClip).toHaveBeenLastCalledWith('CAM_1'); expect(screen.getByText('4.5 s').tagName).toBe('CODE')
  })

  it('starts a new conversation when the project changes, and ignores an answer to the old one', async () => {
    mockGet('/api/agent', status()); let release: () => void = () => {}; const gate = new Promise<void>(r => { release = r })
    mockPost('/api/agent/chat', async () => { await gate; return answer({ answer: 'Old answer.' }) })
    const { user, rerender } = setup(<AskPage {...props} />); await ask(user, 'old question')
    rerender(<AskPage {...props} folder="/other" />); expect(screen.queryByText('old question')).not.toBeInTheDocument()
    release(); await vi.waitFor(() => expect(screen.queryByText('Looking…')).not.toBeInTheDocument()); expect(screen.queryByText('Old answer.')).not.toBeInTheDocument()
  })

  it('sends edits only when "Allow edits" is ticked, and says so in the header', async () => {
    mockGet('/api/agent', status()); const seen = recordRequests('/api/agent/chat'); mockPost('/api/agent/chat', answer())
    const { user } = setup(<AskPage {...props} />)
    const box = await screen.findByRole('checkbox', { name: /Allow edits/ }); expect(box).not.toBeChecked(); expect(screen.getByText(/read only/)).toBeInTheDocument()
    await ask(user, 'a'); await screen.findByText('There are 3 clips.'); await user.click(box); expect(screen.getByText(/edits allowed/)).toBeInTheDocument(); await ask(user, 'b'); await vi.waitFor(() => expect(seen).toHaveLength(2))
    expect(seen.map(s => (s.body as { write: boolean }).write)).toEqual([false, true])
  })

  it('shows what waits for approval when the page opens, and an answer can add to it', async () => {
    mockGet('/api/agent', status()); let queue = [pend()]; mockGet('/api/agent/pending', () => ({ pending: queue })); mockPost('/api/agent/chat', () => { queue = [pend(), pend({ id: 'p2', summary: 'forget 2 analysis results' })]; return answer({ pending: queue }) })
    const { user } = setup(<AskPage {...props} />)
    const list = await screen.findByRole('list', { name: 'Waiting for your approval' }); expect(within(list).getAllByRole('listitem')).toHaveLength(1); expect(within(list).getByText(/a long, heavy render/)).toBeInTheDocument()
    await ask(user, 'render it'); await vi.waitFor(() => expect(within(screen.getByRole('list', { name: 'Waiting for your approval' })).getAllByRole('listitem')).toHaveLength(2))
  })

  it('approving runs it through the server and reports what was done', async () => {
    mockGet('/api/agent', status()); let queue = [pend()]; mockGet('/api/agent/pending', () => ({ pending: queue })); const seen = recordRequests('/api/agent/approve'); mockPost('/api/agent/approve', () => { queue = []; return { ok: true, did: 'start the final film render', job: true, backup: null } })
    const { user } = setup(<AskPage {...props} />); await user.click(await screen.findByRole('button', { name: 'Approve' }))
    expect(await screen.findByText(/Approved and done: start the final film render\. It runs in the background\./)).toBeInTheDocument(); expect(seen[0].body).toEqual({ folder: '/f', id: 'p1' })
    expect(screen.queryByRole('list', { name: 'Waiting for your approval' })).not.toBeInTheDocument()
  })

  it('denying tells the server and drops the card', async () => {
    mockGet('/api/agent', status()); let queue = [pend()]; mockGet('/api/agent/pending', () => ({ pending: queue })); const seen = recordRequests('/api/agent/deny'); mockPost('/api/agent/deny', () => { queue = []; return { denied: true } })
    const { user } = setup(<AskPage {...props} />); await user.click(await screen.findByRole('button', { name: 'Deny' }))
    expect(await screen.findByText(/Denied: start the final film render/)).toBeInTheDocument(); expect(seen[0].body).toEqual({ folder: '/f', id: 'p1' }); expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('shows an approval that failed, and drops the stale card (it is gone on the server)', async () => {
    mockGet('/api/agent', status()); let calls = 0; mockGet('/api/agent/pending', () => ({ pending: calls++ === 0 ? [pend()] : [] })); mockError('/api/agent/approve', 404, 'that approval is gone (expired or already answered)', 'post')
    const { user } = setup(<AskPage {...props} />); await user.click(await screen.findByRole('button', { name: 'Approve' }))
    expect(await screen.findByText(/that approval is gone/)).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('offers one-click undo when the assistant has changed things, and says where the replaced state went', async () => {
    mockGet('/api/agent', status()); mockGet('/api/agent/journal', { entries: [], undo: undoState({ changes: 3 }) }); const seen = recordRequests('/api/agent/undo')
    mockPost('/api/agent/undo', { restored: 'meta-1.tar.gz', checkpoint: 'meta-2.tar.gz', files: 5, undone: 3 })
    const { user } = setup(<AskPage {...props} />)
    expect(await screen.findByText(/The assistant made 3 changes/)).toBeInTheDocument()
    mockGet('/api/agent/journal', { entries: [], undo: undoState({ available: false, changes: 0 }) }); await user.click(screen.getByRole('button', { name: 'Undo them' }))
    expect(await screen.findByText(/Undone: the project is back to before the assistant's last 3 changes \(5 files restored\)\. The state just before the undo is saved as meta-2\.tar\.gz/)).toBeInTheDocument()
    expect(seen[0].body).toEqual({ folder: '/f' }); await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Undo them' })).not.toBeInTheDocument())
  })

  it('shows no undo when there is nothing to undo, and an undo that fails says why', async () => {
    mockGet('/api/agent', status()); setup(<AskPage {...props} />); await screen.findByLabelText('Your question'); expect(screen.queryByRole('button', { name: 'Undo them' })).not.toBeInTheDocument()
    mockGet('/api/agent/journal', { entries: [], undo: undoState() }); mockError('/api/agent/undo', 409, 'the backup meta-1.tar.gz is gone', 'post')
    const { user } = setup(<AskPage {...props} />); await user.click(await screen.findByRole('button', { name: 'Undo them' })); expect(await screen.findByText(/the backup meta-1\.tar\.gz is gone/)).toBeInTheDocument()
  })

  it('picks up an approval an outside agent asked for while the page is open', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true }); try {
      mockGet('/api/agent', status()); setup(<AskPage {...props} />); await screen.findByLabelText('Your question'); expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
      mockGet('/api/agent/pending', { pending: [pend({ summary: 'asked by Claude Code' })] }); await act(() => vi.advanceTimersByTimeAsync(5200))
      expect(await screen.findByText(/asked by Claude Code/)).toBeInTheDocument()
    } finally { vi.useRealTimers() }
  })

  it('has no accessibility violations with an approval waiting', async () => {
    mockGet('/api/agent', status()); mockGet('/api/agent/pending', { pending: [pend()] }); const { container } = setup(<AskPage {...props} />)
    await screen.findByRole('button', { name: 'Approve' }); expect(await axe(container)).toHaveNoViolations()
  })

  it('has no accessibility violations and a labelled conversation log', async () => {
    mockGet('/api/agent', status()); mockPost('/api/agent/chat', answer({ images: [{ url: '/x.jpg', caption: 'a picture' }], steps: [{ tool: 'clips', args: {}, seconds: 0.1, chars: 1, error: null }] }))
    const { user, container } = setup(<AskPage {...props} />); await ask(user, 'q'); await screen.findByRole('img', { name: 'a picture' })
    expect(within(screen.getByRole('log', { name: 'Conversation' })).getByText('There are 3 clips.')).toBeInTheDocument(); expect(await axe(container)).toHaveNoViolations()
  })
})

describe('inline', () => {
  const render = (text: string, ids: string[] = []) => inline(text, ids, () => {})
  it('leaves plain text alone', () => expect(render('hello world')).toEqual(['hello world']))
  it('prefers the longest clip id when ids share a prefix', () => {
    const out = inline('CAM_10 and CAM_1', ['CAM_1', 'CAM_10'], () => {}).filter(Boolean); expect(out.filter(n => typeof n !== 'string')).toHaveLength(2)
  })
  it('does not treat regular expression characters in ids as patterns', () => expect(() => render('a.b and (x)', ['a.b', '(x)'])).not.toThrow())
})
