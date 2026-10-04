import type { Poi } from '../api'
import { stopFacts } from '../mapLayers'

/** The stops of the run away from the checkpoints, the start and the finish: the run stayed within a small place for ten minutes or more. The same facts as the card on the map. */
export default function StopsTable({ pois, tz }: { pois: Poi[]; tz: string }) {
  const stops = pois.filter(p => p.sym === 'stop')
  return (
    <div className="mt-3" aria-label="Other stops">
      <h3 className="text-sm font-semibold">Other stops <span className="font-normal text-stone-500">({stops.length})</span></h3>
      {stops.length === 0 ? <p className="text-sm text-stone-500">No stop of ten minutes or more in one small place (within 60 m) away from the checkpoints, the start and the finish.</p> : (
        <table className="mt-1 w-full text-left text-sm">
          <thead className="text-xs text-stone-500"><tr><th className="pr-3">Stop</th><th className="pr-3">Km</th><th className="pr-3">From</th><th className="pr-3">To</th><th className="pr-3">Stopped</th><th>Within</th></tr></thead>
          <tbody>{stops.map(p => { const f = stopFacts(p, tz); return (
            <tr key={p.name} data-stop-row={p.name} className="border-t border-stone-100 dark:border-stone-800"><td className="py-0.5 pr-3 font-medium">{f.name}</td><td className="pr-3">{f.km ?? '–'}</td><td className="pr-3">{f.arrived}</td><td className="pr-3">{f.left}</td><td className="pr-3">{f.duration}</td><td>{f.area_m} m</td></tr>) })}</tbody>
        </table>
      )}
    </div>
  )
}
