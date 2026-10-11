import { createRef } from 'react'
import { expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import { mockError, mockGet, mockPost, recordRequests } from '../utils/api'
import { setup, screen, waitFor, within } from '../utils/render'
import { stubBrowserApis } from '../utils/media'
import FilmText from '../../src/components/FilmText'
import { makeFilmText, makeTextCard, makeTextElement } from '../utils/factories'

stubBrowserApis()

const player = (t = 12.34) => {
  const v = document.createElement('video'); Object.defineProperty(v, 'currentTime', { value: t, writable: true }); v.play = vi.fn(() => Promise.resolve())
  const ref = createRef<HTMLVideoElement>(); (ref as { current: HTMLVideoElement | null }).current = v; return { v, ref }
}
const withCards = (...cards: ReturnType<typeof makeTextCard>[]) => mockGet('/api/film/text', makeFilmText({ cards }))

it('says there is no text yet and offers to add some', async () => {
  const { ref } = player(); setup(<FilmText folder="/f" video={ref} />)
  expect(await screen.findByText(/No on-screen text yet/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Add text at the player position' })).toBeInTheDocument()
})

it('lists each card with its time, words, details and two pictures', async () => {
  withCards(makeTextCard(), makeTextCard({ id: 'u7', user: true, t: 10, lines: [{ role: 'title', text: 'GO' }], blocking: { score: 4, what: 'covers 20% of a face' } }))
  const { ref } = player(); setup(<FilmText folder="/f" video={ref} />)
  expect(await screen.findByText('HALFWAY')).toBeInTheDocument()
  expect(screen.getByText('2 cards')).toBeInTheDocument()
  expect(screen.getByText(/progress · 3.4 s/)).toBeInTheDocument()
  expect(screen.getByText(/progress · by hand · 3.4 s/)).toBeInTheDocument()
  expect(screen.getByText(/blocks 4.0 \(covers 20% of a face\)/)).toBeInTheDocument()
  const pic = screen.getByAltText('HALFWAY on the film') as HTMLImageElement
  expect(pic.src).toContain('/api/film/text/still'); expect(pic.src).toContain('mode=still')
  expect(screen.getByAltText('HALFWAY by itself')).toBeInTheDocument()
})

it('plays the film from the time of a card when its time is clicked', async () => {
  withCards(makeTextCard()); const { v, ref } = player(0); const { user } = setup(<FilmText folder="/f" video={ref} />)
  await user.click(await screen.findByRole('button', { name: /Play the film from 1:35.9/ }))
  expect(v.currentTime).toBe(95.9); expect(v.play).toHaveBeenCalled()
})

it('draws the pictures of a card again when Preview is pressed', async () => {
  withCards(makeTextCard()); const { ref } = player(); const { user } = setup(<FilmText folder="/f" video={ref} />)
  const before = ((await screen.findByAltText('HALFWAY on the film')) as HTMLImageElement).src
  await user.click(screen.getByRole('button', { name: 'Preview HALFWAY' }))
  await waitFor(() => expect((screen.getByAltText('HALFWAY on the film') as HTMLImageElement).src).not.toBe(before))
})

it('changes a card and saves it, then draws its pictures again', async () => {
  withCards(makeTextCard()); const seen = recordRequests('/api/film/text/save'); mockPost('/api/film/text/save', makeTextCard({ lines: [{ role: 'title', text: 'MIDWAY' }] }))
  const { ref } = player(); const { user } = setup(<FilmText folder="/f" video={ref} />)
  const before = ((await screen.findByAltText('HALFWAY on the film')) as HTMLImageElement).src
  await user.click(screen.getByRole('button', { name: 'Edit HALFWAY' }))
  const form = screen.getByRole('form', { name: 'Edit text' }); const text = within(form).getByLabelText('Text'); await user.clear(text); await user.type(text, 'MIDWAY')
  await user.click(within(form).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(seen.find(s => s.method === 'POST')).toBeTruthy())
  const body = seen.find(s => s.method === 'POST')!.body as { folder: string; card: { id: string; t: number; dur_s: number; elements: { text: string }[] } }
  expect(body.folder).toBe('/f'); expect(body.card).toMatchObject({ id: 'o1', t: 95.9, dur_s: 3.4 }); expect(body.card.elements[0].text).toBe('MIDWAY')
  expect(await screen.findByText(/Saved MIDWAY/)).toBeInTheDocument()
  await waitFor(() => expect((screen.getByAltText('HALFWAY on the film') as HTMLImageElement).src).not.toBe(before))
})

it('makes a new card at the player position', async () => {
  const seen = recordRequests('/api/film/text/save'); mockPost('/api/film/text/save', makeTextCard({ id: 'u1', user: true }))
  const { ref } = player(12.34); const { user } = setup(<FilmText folder="/f" video={ref} />)
  await user.click(await screen.findByRole('button', { name: 'Add text at the player position' }))
  const form = screen.getByRole('form', { name: 'New text' }); expect(within(form).getByLabelText(/Starts at/)).toHaveValue(12.3)
  await user.type(within(form).getByLabelText('Words'), 'LOADS OF IT'); await user.click(within(form).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(seen.find(s => s.method === 'POST')).toBeTruthy())
  expect(seen.find(s => s.method === 'POST')!.body).toEqual({ folder: '/f', card: { t: 12.3, dur_s: 3, start_s: 0.15, texts: ['LOADS OF IT'] } })
})

it('takes the start of a card from the player on request', async () => {
  withCards(makeTextCard()); const { v, ref } = player(5); const { user } = setup(<FilmText folder="/f" video={ref} />)
  await user.click(await screen.findByRole('button', { name: 'Edit HALFWAY' })); v.currentTime = 40.04
  await user.click(screen.getByRole('button', { name: 'Use player position' })); expect(screen.getByLabelText(/Starts at/)).toHaveValue(40)
})

it('deletes a card after asking', async () => {
  withCards(makeTextCard()); const seen = recordRequests('/api/film/text/delete'); mockPost('/api/film/text/delete', { ok: true }); const ask = vi.spyOn(window, 'confirm').mockReturnValue(true)
  const { ref } = player(); const { user } = setup(<FilmText folder="/f" video={ref} />)
  await user.click(await screen.findByRole('button', { name: 'Delete HALFWAY' })); expect(ask).toHaveBeenCalled()
  await waitFor(() => expect(seen.find(s => s.method === 'POST')?.body).toEqual({ folder: '/f', id: 'o1' })); expect(await screen.findByText('Deleted')).toBeInTheDocument()
  ask.mockReturnValue(false); seen.length = 0; await user.click(screen.getByRole('button', { name: 'Delete HALFWAY' })); expect(seen).toHaveLength(0)
})

it('shows what the server refused', async () => {
  withCards(makeTextCard({ elements: [makeTextElement()] })); mockError('/api/film/text/save', 400, 'the start must be inside the film (0 to 252.0 s)', 'post')
  const { ref } = player(); const { user } = setup(<FilmText folder="/f" video={ref} />)
  await user.click(await screen.findByRole('button', { name: 'Edit HALFWAY' })); await user.click(within(screen.getByRole('form', { name: 'Edit text' })).getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('inside the film')
})

it('warns when the cards were made for an earlier plan and when there is no preview', async () => {
  mockGet('/api/film/text', makeFilmText({ cards: [makeTextCard()], stale: true, has_preview: false })); const { ref } = player(); setup(<FilmText folder="/f" video={ref} />)
  expect(await screen.findByText(/earlier plan/)).toBeInTheDocument(); expect(screen.getByText(/Render the film preview to see each card/)).toBeInTheDocument()
})

it('has no accessibility violations with a card open for editing', async () => {
  withCards(makeTextCard()); const { ref } = player(); const { user, container } = setup(<FilmText folder="/f" video={ref} />)
  await user.click(await screen.findByRole('button', { name: 'Edit HALFWAY' })); expect(await axe(container)).toHaveNoViolations()
})
