import { useState } from 'react'
import { api } from './api'
import { usePoll } from './usePoll'

/** The film's text cards, shared by the player's overlay and the list under it: `reload` asks again at once (after a save or a delete). */
export function useFilmText(folder: string) {
  const [version, setVersion] = useState(0)
  const list = usePoll(() => api.filmText(folder), 6000, [folder, version])
  return { list, reload: () => setVersion(n => n + 1) }
}

/** A short key of what a card looks like: when it changes, the picture of it is fetched again. */
export function cardKey(c: { id: string; t: number; dur_s: number; elements: unknown[] }): string {
  const s = JSON.stringify([c.t, c.dur_s, c.elements]); let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return `${c.id}.${(h >>> 0).toString(36)}`
}
