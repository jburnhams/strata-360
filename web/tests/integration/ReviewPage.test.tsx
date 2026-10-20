import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewPage from '../../src/components/ReviewPage'
import { setup, screen, waitFor } from '../utils/render'
import { stubMedia } from '../utils/media'
import { mockError, mockGet, mockPending, recordRequests } from '../utils/api'
import { makeReviewItem, makeReviewQueue } from '../utils/factories'

const queue = (...items: ReturnType<typeof makeReviewItem>[]) => makeReviewQueue({ items, todo: items.filter(i => !i.reviewed).length, total: items.length })

describe('ReviewPage', () => {
  let media: ReturnType<typeof stubMedia>
  let audio: HTMLAudioElement | null
  beforeEach(() => {
    media = stubMedia(); audio = null
    media.play.mockImplementation(function (this: HTMLMediaElement) { audio = this as HTMLAudioElement; return Promise.resolve() })          // the player's one audio element lives across tests, and load() is skipped when the sound is the same
    media.load.mockImplementation(function (this: HTMLMediaElement) { audio = this as HTMLAudioElement; setTimeout(() => this.dispatchEvent(new Event('loadedmetadata')), 0) })
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('shows a placeholder while the queue loads', () => {
    mockPending('/api/transcript/review'); setup(<ReviewPage folder="f" />)
    expect(screen.getByLabelText('Loading Review the transcript')).toBeInTheDocument()
  })

  it('says so when no speech has been recognised', async () => {
    mockGet('/api/transcript/review', makeReviewQueue({ items: [], todo: 0, total: 0 })); setup(<ReviewPage folder="f" />)
    expect(await screen.findByText('No speech recognised yet.')).toBeInTheDocument()
  })

  it('says so when everything has been looked at', async () => {
    mockGet('/api/transcript/review', queue(makeReviewItem({ reviewed: true }))); setup(<ReviewPage folder="f" />)
    expect(await screen.findByText('Nothing left to look at.')).toBeInTheDocument()
  })

  it('shows a phrase with its pace, confidence and unsure words, and a box with the text', async () => {
    setup(<ReviewPage folder="f" />)
    expect(await screen.findByText('5.1 w/s · 306 wpm')).toBeInTheDocument()
    expect(screen.getByText('50% sure')).toBeInTheDocument()
    expect(screen.getByText('1 of 3 words unsure')).toBeInTheDocument()
    expect(screen.getByText('1 to look at of 1 phrases')).toBeInTheDocument()
    expect(screen.getByLabelText('what was said')).toHaveValue('we wear fine')
    expect(screen.getByText('wear')).toHaveAttribute('title', '30% sure')
  })

  it('shows the recogniser flags, a foreign language and missing numbers', async () => {
    mockGet('/api/transcript/review', queue(makeReviewItem({ flags: ['probably_no_speech'], lang: 'fr', wps: null, logprob: null, low_words: 0, play_rate: 1 }))); setup(<ReviewPage folder="f" />)
    expect(await screen.findByText('probably no speech')).toBeInTheDocument()
    expect(screen.getByText('FR')).toBeInTheDocument(); expect(screen.getByText('pace n/a')).toBeInTheDocument(); expect(screen.getByText('confidence n/a')).toBeInTheDocument()
  })

  it('plays the phrase at the original speed and, for fast speech, slowed to a normal pace', async () => {
    const { user } = setup(<ReviewPage folder="f" />)
    await user.click(await screen.findByRole('button', { name: /slowed to normal pace \(×0.69\)/ }))
    await waitFor(() => expect(media.play).toHaveBeenCalled())
    expect(audio!.playbackRate).toBe(0.69); expect(audio!.currentTime).toBe(1.7); expect(audio!.src).toContain('kind=clean')
    await user.click(screen.getByRole('button', { name: /original speed/ }))
    await waitFor(() => expect(audio!.playbackRate).toBe(1))
    await user.click(screen.getByRole('button', { name: /original speed/ }))      // pressed again: stops
    await waitFor(() => expect(media.pause).toHaveBeenCalled())
  })

  it('shows where the phrase is on a timeline and lights the word being heard while it plays', async () => {
    const { user } = setup(<ReviewPage folder="f" />)
    const line = await screen.findByRole('img', { name: /the phrase runs from 0:03 to 0:04 of the clip; the player plays from 0:01 to 0:05/ })
    expect(line).toBeInTheDocument(); expect(screen.queryByTestId('playhead')).not.toBeInTheDocument()       // the sound before and after the phrase is on the bar, the phrase itself marked inside it
    await user.click(screen.getByRole('button', { name: /original speed/ })); await waitFor(() => expect(media.play).toHaveBeenCalled())
    audio!.currentTime = 3.7                                                                                    // inside "wear"
    await waitFor(() => expect(screen.getByText('wear')).toHaveAttribute('aria-current', 'true'))
    expect(screen.getByText('we')).not.toHaveAttribute('aria-current'); expect(screen.getByTestId('playhead').style.left).toBe(`${((3.7 - 1.7) / 4.2) * 100}%`)
    audio!.currentTime = 2.0                                                                                    // the lead-in: no word yet
    await waitFor(() => expect(screen.queryByText('wear')).not.toHaveAttribute('aria-current')); expect(screen.getByText('we')).not.toHaveAttribute('aria-current')
    await user.click(screen.getByRole('button', { name: /original speed/ }))
  })

  it('repeats the phrase until stopped, unless looping is switched off (one setting for every player)', async () => {
    mockGet('/api/transcript/review', queue(makeReviewItem({ si: 0 }), makeReviewItem({ si: 1 }))); const { user } = setup(<ReviewPage folder="f" />)
    const loops = await screen.findAllByRole('button', { name: /loop/ }); expect(loops).toHaveLength(2); loops.forEach(b => expect(b).toHaveAttribute('aria-pressed', 'true'))      // on by default
    await user.click(screen.getAllByRole('button', { name: /original speed/ })[0]); await waitFor(() => expect(media.play).toHaveBeenCalled())
    media.pause.mockClear(); audio!.currentTime = 5.95                                                          // past the end of the span (5.9)
    await waitFor(() => expect(audio!.currentTime).toBeLessThan(2)); expect(audio!.currentTime).toBeGreaterThanOrEqual(1.7); expect(media.pause).not.toHaveBeenCalled()      // back at its start, still playing
    await user.click(loops[1]); loops.forEach(b => expect(b).toHaveAttribute('aria-pressed', 'false'))          // switching it off on one player switches it off on all
    audio!.currentTime = 5.95; await waitFor(() => expect(media.pause).toHaveBeenCalled())                     // now it plays to the end and stops
    await user.click(loops[0]); loops.forEach(b => expect(b).toHaveAttribute('aria-pressed', 'true'))
  })

  it('stops the sound when a correction is saved or the phrase is hidden', async () => {
    mockGet('/api/transcript/review', queue(makeReviewItem({ si: 0 }), makeReviewItem({ si: 1 }))); const { user } = setup(<ReviewPage folder="f" />)
    await user.click((await screen.findAllByRole('button', { name: /original speed/ }))[0]); await waitFor(() => expect(media.play).toHaveBeenCalled())
    media.pause.mockClear(); await user.click(screen.getAllByRole('button', { name: 'looks right' })[0]); await waitFor(() => expect(media.pause).toHaveBeenCalled())
    await user.click(screen.getAllByRole('button', { name: /original speed/ })[0]); await waitFor(() => expect(media.play).toHaveBeenCalledTimes(2))
    media.pause.mockClear(); await user.click(screen.getAllByRole('button', { name: 'hide' })[0]); await waitFor(() => expect(media.pause).toHaveBeenCalled())
  })

  it('has no slowed version for speech that is not fast', async () => {
    mockGet('/api/transcript/review', queue(makeReviewItem({ play_rate: 1, wps: 3 }))); setup(<ReviewPage folder="f" />)
    expect(await screen.findByText('not fast: no slowed version')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /slowed/ })).not.toBeInTheDocument()
  })

  it('plays the original sound when asked', async () => {
    const { user } = setup(<ReviewPage folder="f" />)
    await user.selectOptions(await screen.findByLabelText(/sound/), 'original')
    await user.click(screen.getByRole('button', { name: /original speed/ }))
    await waitFor(() => expect(audio!.src).toContain('kind=original'))
    await user.click(screen.getByRole('button', { name: /original speed/ }))
  })

  it('plays with the keys: Alt+1 at the original speed, Alt+2 slowed, Escape stops', async () => {
    const { user } = setup(<ReviewPage folder="f" />)
    const box = await screen.findByLabelText('what was said'); await user.click(box)
    await user.keyboard('{Alt>}2{/Alt}'); await waitFor(() => expect(audio?.playbackRate).toBe(0.69))
    await user.keyboard('{Alt>}1{/Alt}'); await waitFor(() => expect(audio?.playbackRate).toBe(1))
    await user.keyboard('{Escape}'); await waitFor(() => expect(media.pause).toHaveBeenCalled())
    expect(box).toHaveValue('we wear fine')                           // none of the keys typed anything
  })

  it('stores a retyped phrase as word corrections and takes it off the list', async () => {
    const edits = recordRequests('/api/transcript/edit'), done = recordRequests('/api/transcript/reviewed')
    const { user } = setup(<ReviewPage folder="f" />)
    const box = await screen.findByLabelText('what was said'); await user.clear(box); await user.type(box, 'we are fine')
    await user.click(screen.getByRole('button', { name: 'save correction' }))
    await waitFor(() => expect(done).toHaveLength(1))
    expect(edits.map(e => e.body)).toEqual([{ folder: 'f', clip: 'CAM_20260101120000_0001_D', seg: 0, word: 1, text: 'are' }])
    expect(done[0].body).toMatchObject({ seg: 0, state: true })
  })

  it('saves with Enter', async () => {
    const edits = recordRequests('/api/transcript/edit'), done = recordRequests('/api/transcript/reviewed')
    const { user } = setup(<ReviewPage folder="f" />)
    const box = await screen.findByLabelText('what was said'); await user.type(box, ' now{Enter}')
    await waitFor(() => expect(done).toHaveLength(1)); expect(edits.map(e => (e.body as { text: string }).text)).toEqual(['fine now'])
  })

  it('takes a phrase that is right off the list without any correction', async () => {
    const edits = recordRequests('/api/transcript/edit'), done = recordRequests('/api/transcript/reviewed')
    const { user } = setup(<ReviewPage folder="f" />)
    await user.click(await screen.findByRole('button', { name: 'looks right' }))
    await waitFor(() => expect(done).toHaveLength(1)); expect(edits).toHaveLength(0)
  })

  it('treats Enter on untouched text as "looks right"', async () => {
    const edits = recordRequests('/api/transcript/edit'), done = recordRequests('/api/transcript/reviewed')
    const { user } = setup(<ReviewPage folder="f" />)
    await user.type(await screen.findByLabelText('what was said'), '{Enter}')
    await waitFor(() => expect(done).toHaveLength(1)); expect(edits).toHaveLength(0)
  })

  it('lets you undo your typing, and only offers to save once the text changed', async () => {
    const { user } = setup(<ReviewPage folder="f" />)
    expect(await screen.findByRole('button', { name: 'save correction' })).toBeDisabled()
    const box = screen.getByLabelText('what was said'); await user.type(box, ' x')
    expect(screen.getByRole('button', { name: 'save correction' })).toBeEnabled(); expect(screen.getByText('Enter saves')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'undo my typing' })); expect(box).toHaveValue('we wear fine')
  })

  it('lists the ones already looked at on request and can put one back', async () => {
    const done = recordRequests('/api/transcript/reviewed')
    mockGet('/api/transcript/review', queue(makeReviewItem({ si: 0 }), makeReviewItem({ si: 1, reviewed: true }))); const { user } = setup(<ReviewPage folder="f" />)
    await screen.findAllByLabelText('what was said'); expect(screen.getAllByLabelText('what was said')).toHaveLength(1)
    await user.click(screen.getByRole('checkbox', { name: /show ones I have looked at/ })); expect(screen.getAllByLabelText('what was said')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'put back in the list' }))
    await waitFor(() => expect(done).toHaveLength(1)); expect(done[0].body).toMatchObject({ seg: 1, state: false })
  })

  it('shows corrected words underlined and the error when saving fails', async () => {
    mockGet('/api/transcript/review', queue(makeReviewItem({ words: [{ i: 0, w: 'we', t0: 0, t1: 1, p: 0.9 }, { i: 1, w: 'are', t0: 1, t1: 2, p: 0.2, e: { orig: 'wear', src: 'user' } }, { i: 2, w: '', t0: 2, t1: 3, p: 0.9 }] })))
    mockError('/api/transcript/reviewed', 500, 'disk full', 'post'); const { user } = setup(<ReviewPage folder="f" />)
    expect(await screen.findByLabelText('what was said')).toHaveValue('we are')
    await user.click(screen.getByRole('button', { name: 'looks right' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('disk full')
  })

  it('hides a phrase with one button', async () => {
    const hides = recordRequests('/api/transcript/hide'); const { user } = setup(<ReviewPage folder="f" />)
    await user.click(await screen.findByRole('button', { name: 'hide' }))
    await waitFor(() => expect(hides).toHaveLength(1)); expect(hides[0].body).toEqual({ folder: 'f', clip: 'CAM_20260101120000_0001_D', seg: 0, state: true })
  })

  it('lists a hidden phrase last, whatever the filter, with only a way to show it again', async () => {
    const hides = recordRequests('/api/transcript/hide')
    mockGet('/api/transcript/review', queue(makeReviewItem({ si: 0 }), makeReviewItem({ si: 1, hidden: true, reviewed: true }))); const { user } = setup(<ReviewPage folder="f" />)
    await screen.findByText('hidden'); expect(screen.getAllByLabelText('what was said')).toHaveLength(1)           // the hidden one has no box to retype it, and is listed although "show ones I have looked at" is off
    expect(screen.getAllByRole('button', { name: 'hide' })).toHaveLength(1); expect(screen.queryByRole('button', { name: 'looks right' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'show again' }))
    await waitFor(() => expect(hides).toHaveLength(1)); expect(hides[0].body).toMatchObject({ seg: 1, state: false })
  })

  it('shows the error when hiding fails', async () => {
    mockError('/api/transcript/hide', 500, 'disk full', 'post'); const { user } = setup(<ReviewPage folder="f" />)
    await user.click(await screen.findByRole('button', { name: 'hide' })); expect(await screen.findByRole('alert')).toHaveTextContent('disk full')
  })

  it('shows twenty at a time', async () => {
    mockGet('/api/transcript/review', queue(...Array.from({ length: 25 }, (_, i) => makeReviewItem({ si: i })))); const { user } = setup(<ReviewPage folder="f" />)
    await screen.findAllByLabelText('what was said'); expect(screen.getAllByLabelText('what was said')).toHaveLength(20)
    await user.click(screen.getByRole('button', { name: 'show 5 more' })); expect(screen.getAllByLabelText('what was said')).toHaveLength(25)
  })

  it('opens the clip at the phrase', async () => {
    const onOpen = vi.fn(); const { user } = setup(<ReviewPage folder="f" onOpen={onOpen} />)
    await user.click(await screen.findByTitle('open the clip at this moment')); expect(onOpen).toHaveBeenCalledWith('CAM_20260101120000_0001_D', 3.2)
  })
})
