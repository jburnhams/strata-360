import type { Poi } from '../api'
import { stopFacts } from '../mapLayers'
import { Button } from 'strata-react'

/** The stops of the run away from the checkpoints, the start and the finish: the run stayed within a small place for ten minutes or more. The same facts as the card on the map. */
export default function StopsTable({ pois, tz, onToggle, onOpenGap }: { pois: Poi[]; tz: string; onToggle?: (key: string, add: boolean) => void | Promise<void>; onOpenGap?: (gap: string) => void }) {
  const stops = pois.filter(p => p.sym === 'stop')
  return (
    <div className="mt-3" aria-label="Other stops">
      <h3 className="type-body-sm font-semibold">Other stops <span className="font-normal text-muted-foreground">({stops.length})</span></h3>
      {stops.length === 0 ? <p className="type-body-sm text-muted-foreground">No stop of ten minutes or more in one small place (within 60 m) away from the checkpoints, the start and the finish.</p> : (
        <table className="mt-1 w-full text-left type-body-sm">
          <thead className="type-caption text-muted-foreground"><tr><th className="pr-3">Stop</th><th className="pr-3">Km</th><th className="pr-3">From</th><th className="pr-3">To</th><th className="pr-3">Stopped</th><th className="pr-3">Within</th><th>In the video</th></tr></thead>
          <tbody>{stops.map(p => { const f = stopFacts(p, tz); return (
            <tr key={p.name} data-stop-row={p.name} className="border-t border-border"><td className="py-0.5 pr-3 font-medium">{f.name}</td><td className="pr-3">{f.km ?? '–'}</td><td className="pr-3">{f.arrived}</td><td className="pr-3">{f.left}</td><td className="pr-3">{f.duration}</td><td className="pr-3">{f.area_m} m</td><td>{p.added
              ? <span className="flex items-center gap-2">{p.gap && onOpenGap ? <Button variant="link" onClick={() => onOpenGap(p.gap!)}>as {p.gap}</Button> : p.gap ? <span>as {p.gap}</span> : <span title="The footage covers the stop and its lead-in and lead-out: there is no time left for a clip">covered by footage</span>}<Button variant="link" aria-label={`Take ${f.name} out of the video`} onClick={() => p.key && onToggle?.(p.key, false)}>remove</Button></span>
              : <Button size="sm" aria-label={`Add ${f.name} to the video`} onClick={() => p.key && onToggle?.(p.key, true)}>Add to video</Button>}</td></tr>) })}</tbody>
        </table>
      )}
    </div>
  )
}
