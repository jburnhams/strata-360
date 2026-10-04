import type { Poi } from '../api'
import { stopFacts } from '../mapLayers'

/** The stops of the run away from the checkpoints, the start and the finish: the run stayed within a small place for ten minutes or more. The same facts as the card on the map. */
export default function StopsTable({ pois, tz, onToggle, onOpenGap }: { pois: Poi[]; tz: string; onToggle?: (key: string, add: boolean) => void | Promise<void>; onOpenGap?: (gap: string) => void }) {
  const stops = pois.filter(p => p.sym === 'stop')
  return (
    <div className="mt-3" aria-label="Other stops">
      <h3 className="text-sm font-semibold">Other stops <span className="font-normal text-stone-500">({stops.length})</span></h3>
      {stops.length === 0 ? <p className="text-sm text-stone-500">No stop of ten minutes or more in one small place (within 60 m) away from the checkpoints, the start and the finish.</p> : (
        <table className="mt-1 w-full text-left text-sm">
          <thead className="text-xs text-stone-500"><tr><th className="pr-3">Stop</th><th className="pr-3">Km</th><th className="pr-3">From</th><th className="pr-3">To</th><th className="pr-3">Stopped</th><th className="pr-3">Within</th><th>In the video</th></tr></thead>
          <tbody>{stops.map(p => { const f = stopFacts(p, tz); return (
            <tr key={p.name} data-stop-row={p.name} className="border-t border-stone-100 dark:border-stone-800"><td className="py-0.5 pr-3 font-medium">{f.name}</td><td className="pr-3">{f.km ?? '–'}</td><td className="pr-3">{f.arrived}</td><td className="pr-3">{f.left}</td><td className="pr-3">{f.duration}</td><td className="pr-3">{f.area_m} m</td><td>{p.added
              ? <span className="flex items-center gap-2">{p.gap && onOpenGap ? <button className="underline" onClick={() => onOpenGap(p.gap!)}>as {p.gap}</button> : <span>added</span>}<button className="text-stone-500 underline" aria-label={`Take ${f.name} out of the video`} onClick={() => p.key && onToggle?.(p.key, false)}>remove</button></span>
              : <button aria-label={`Add ${f.name} to the video`} className="rounded border border-stone-300 px-2 py-0.5 text-xs dark:border-stone-600" onClick={() => p.key && onToggle?.(p.key, true)}>Add to video</button>}</td></tr>) })}</tbody>
        </table>
      )}
    </div>
  )
}
