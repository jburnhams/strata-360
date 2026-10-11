import { createRef } from 'react'
import { expect, it, vi } from 'vitest'
import { fireEvent } from '@testing-library/react'
import { mockError, mockPost, recordRequests } from '../utils/api'
import { setup, screen, waitFor } from '../utils/render'
import { stubBrowserApis } from '../utils/media'
import TextOverlay from '../../src/components/TextOverlay'
import { cardKey } from '../../src/useFilmText'
import { makeFilmText, makeTextCard, makeTextElement } from '../utils/factories'

stubBrowserApis()

const card = makeTextCard({ t: 10, dur_s: 3, boxes: [[0.4, 0.3, 0.6, 0.5], [0.4, 0.6, 0.6, 0.7]], elements: [makeTextElement({ text: 'HALFWAY', x: 0.5, y: 0.4 }), makeTextElement({ text: 'KM 194', x: 0.5, y: 0.65 })] })
const video = (t: number) => { const v = document.createElement('video'); Object.defineProperty(v, 'currentTime', { value: t, writable: true }); const ref = createRef<HTMLVideoElement>(); (ref as { current: HTMLVideoElement | null }).current = v; return { v, ref } }
const mount = (t: number, cards = [card]) => { const { v, ref } = video(t), reload = vi.fn(); const r = setup(<TextOverlay folder="/f" video={ref} list={makeFilmText({ cards })} reload={reload} />); return { ...r, v, reload } }
const size = (el: HTMLElement) => { const box = el.closest('div[style*="aspect-ratio"]') as HTMLElement; box.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, width: 1000, height: 562.5, right: 1000, bottom: 562.5, toJSON: () => ({}) }) }

it('offers a handle for each word of a card while the card is on', async () => {
  mount(11)
  expect(await screen.findByRole('button', { name: 'Move HALFWAY' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Move KM 194' })).toBeInTheDocument()
})

it('offers nothing when no card is on', async () => {
  const { v } = mount(2); await new Promise(r => setTimeout(r, 80)); expect(screen.queryByRole('button', { name: /Move/ })).toBeNull(); v.currentTime = 11
  expect(await screen.findByRole('button', { name: 'Move HALFWAY' })).toBeInTheDocument()
})

it('saves the card with the word moved by the distance it was dragged', async () => {
  const seen = recordRequests('/api/film/text/save'); mockPost('/api/film/text/save', card); const { reload } = mount(11)
  const h = await screen.findByRole('button', { name: 'Move HALFWAY' }); size(h)
  fireEvent.pointerDown(h, { pointerId: 1, clientX: 500, clientY: 200 }); fireEvent.pointerMove(h, { pointerId: 1, clientX: 600, clientY: 256.25 }); fireEvent.pointerUp(h, { pointerId: 1 })
  await waitFor(() => expect(seen.find(s => s.method === 'POST')).toBeTruthy())
  const body = seen.find(s => s.method === 'POST')!.body as { folder: string; card: { id: string; t: number; dur_s: number; elements: { text: string; x: number; y: number }[] } }
  expect(body.card).toMatchObject({ id: 'o1', t: 10, dur_s: 3 }); expect(body.card.elements[0].x).toBeCloseTo(0.6, 3); expect(body.card.elements[0].y).toBeCloseTo(0.5, 3)
  expect(body.card.elements[1]).toMatchObject({ x: 0.5, y: 0.65 })                                                  // the other word stays
  await waitFor(() => expect(reload).toHaveBeenCalled())
})

it('does not save a click that did not move the word', async () => {
  const seen = recordRequests('/api/film/text/save'); mockPost('/api/film/text/save', card); mount(11)
  const h = await screen.findByRole('button', { name: 'Move HALFWAY' }); size(h); fireEvent.pointerDown(h, { pointerId: 1, clientX: 500, clientY: 200 }); fireEvent.pointerUp(h, { pointerId: 1 })
  await new Promise(r => setTimeout(r, 50)); expect(seen).toHaveLength(0)
})

it('moves a word with the arrow keys, further with shift, and keeps it inside the frame', async () => {
  const seen = recordRequests('/api/film/text/save'); mockPost('/api/film/text/save', card); mount(11)
  const h = await screen.findByRole('button', { name: 'Move HALFWAY' }); fireEvent.keyDown(h, { key: 'ArrowRight' })
  await waitFor(() => expect(seen).toHaveLength(1)); expect((seen[0].body as { card: { elements: { x: number }[] } }).card.elements[0].x).toBeCloseTo(0.506, 3)
  fireEvent.keyDown(h, { key: 'ArrowUp', shiftKey: true }); await waitFor(() => expect(seen).toHaveLength(2)); expect((seen[1].body as { card: { elements: { y: number }[] } }).card.elements[0].y).toBeCloseTo(0.37, 3)
})

it('shows what the server refused', async () => {
  mockError('/api/film/text/save', 400, 'a card needs at least one word', 'post'); mount(11)
  fireEvent.keyDown(await screen.findByRole('button', { name: 'Move HALFWAY' }), { key: 'ArrowLeft' }); expect(await screen.findByRole('alert')).toHaveTextContent('at least one word')
})

it('asks for a card\'s picture again only when the card has changed', () => {
  expect(cardKey(card)).toBe(cardKey({ ...card })); expect(cardKey(card)).not.toBe(cardKey({ ...card, t: 11 })); expect(cardKey(card)).not.toBe(cardKey({ ...card, elements: [makeTextElement({ text: 'OTHER' })] }))
  expect(cardKey(card).startsWith('o1.')).toBe(true)
})
