import { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../usePoll'

// The rough mix of the film plan, sound only: the music and the clips' background quietly, the voice-over and the runner's own speech up. Make it, then play it here to hear the script's pacing
// without rendering any picture. It is made again (a minute or so) whenever the plan, the voice-over or the music has changed.
export default function RoughMixPlayer({ folder, version = 0 }: { folder: string; version?: number }) {
  const [tick, setTick] = useState(0)
  const [err, setErr] = useState<string>()
  const mix = usePoll(() => api.roughMix(folder), 3000, [folder, tick, version])
  if (!mix || !mix.has_plan) return null
  const make = async () => {
    setErr(undefined)
    try { const r = await api.makeRoughMix(folder); if (!r.started) setErr(r.reason ?? 'could not start') } catch (e) { setErr((e as Error).message) }
    setTick(t => t + 1)
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
      <button disabled={mix.building} className="rounded-lg border border-stone-400 px-3 py-1.5 disabled:opacity-50" title="the film's sound alone: music and clip background quiet, voice-over and speech up" onClick={() => void make()}>
        {mix.building ? 'Making the rough mix…' : mix.exists ? (mix.stale ? 'Make the rough mix again' : 'Remake the rough mix') : 'Make a rough mix'}
      </button>
      {mix.building && <span className="font-mono text-xs text-stone-500">{mix.log}</span>}
      {mix.exists && <audio aria-label="Rough mix" controls preload="none" src={api.roughMixUrl(folder, mix.made_at ?? '')} className="h-9" />}
      {mix.exists && mix.stale && !mix.building && <span className="text-xs text-amber-700">out of date: the plan, voice-over or music has changed since</span>}
      {(err || (!mix.building && mix.error)) && <span role="alert" className="text-xs text-red-600">{err ?? `The rough mix failed: ${mix.error}`}</span>}
    </div>
  )
}
