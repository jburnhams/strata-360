import { useSyncExternalStore } from 'react'
import type { ClipInfo } from './api'

// "Overlay on thumbnails": one switch for the whole app, remembered in this browser. When on, thumbnails are asked for in their race-overlay version (the thumb_overlay
// stage); the server sends the plain one when that version is missing or out of date.
const KEY = 'strata360.thumbOverlay'
const listeners = new Set<() => void>()

function read(): boolean {
  try { return globalThis.localStorage?.getItem(KEY) === '1' } catch { return false }
}

let on = read()

export function setThumbOverlay(v: boolean) {
  on = v
  try { globalThis.localStorage?.setItem(KEY, v ? '1' : '0') } catch { /* private window or blocked storage: the switch still works until reload */ }
  listeners.forEach(l => l())
}

export const thumbOverlay = () => on

function subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l) } }

/** The `v` of a thumbnail URL: changes when the overlay version is shown or appears, so the browser does not keep the plain picture. */
export const thumbVersion = (c: Pick<ClipInfo, 'thumb' | 'thumb_overlay'>, overlay: boolean) => `${c.thumb}${overlay && c.thumb_overlay ? '+overlay' : ''}`

export function useThumbOverlay(): [boolean, (v: boolean) => void] {
  return [useSyncExternalStore(subscribe, thumbOverlay, thumbOverlay), setThumbOverlay]
}
