import { useMemo, useState } from 'react'
import { api, type SvChoice, type SvChosen } from '../api'
import { usePoll } from '../usePoll'
import ItemPage, { LengthField } from './ItemPage'
import TrackMap from './TrackMap'
import { PointCamTool, usePointCams } from './PointCams'
import { ChoiceRadios, SectionContent, SectionFacts } from './StreetViewPage'

// A street view section used in the film as a page of its own, with the sections of a gap or a photo (ItemPage) and, as the preview, everything the street view page shows for it: when it was filmed and passed, the light, the
// footage near it, the camera, the preview video and the pictures. The choice (not used, possible, must include) is here too.
export default function SvItemPage({ folder, item, tz, onChanged }: { folder: string; item?: SvChosen; tz: string; onChanged: () => void }) {
  const [err, setErr] = useState<string>(), [tick, setTick] = useState(0)
  const data = usePoll(() => api.streetview(folder), 8000, [folder, tick])
  const pc = usePointCams(folder, { kind: 'streetview', key: item?.key ?? '' })
  const its = data?.sections.find(x => x.key === item?.key)?.items ?? [], sig = `${item?.key}:${its.length}:${its[0]?.id}`
  const frames = useMemo(() => its.map((it, i) => ({ lat: it.lat, lon: it.lon, label: `Picture ${i + 1} of ${its.length} · km ${it.km}` })), [sig])         // eslint-disable-line react-hooks/exhaustive-deps  (where each picture was taken: the same list until the section changes, so the map is not redrawn and moved by every refresh)
  if (!item) return <p className="text-sm text-stone-500">That street view section is not chosen for the film any more.</p>
  const section = data?.sections.find(x => x.key === item.key), by = new Map((data?.sections ?? []).map(x => [x.id, x]))
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } setTick(t => t + 1); onChanged() }
  const choose = (key: string, c: SvChoice | 'none') => run(() => api.setStreetviewChoice(folder, key, c))
  const names = { mapillary: 'Mapillary', panoramax: 'Panoramax', google: 'Google' }
  return (
    <ItemPage folder={folder} noun="street view section" must={item.choice === 'must'} script={item.script} err={err} noteClip={item.label} noteTitle="Notes for this street view section" notePlaceholder="What is this road? What was it like to run, what to mention or avoid…"
      heading={<>Street view {item.label} <span className="text-sm font-normal text-stone-500">{names[item.provider]} · {item.kind === '360' ? '360°' : '2D'} · {Math.round(item.length_m)} m</span></>}
      sub={item.quality ? `clip quality: ${item.quality}` : undefined}
      where={<PointCamTool folder={folder} source={{ kind: 'streetview', key: item.key }} pc={pc} unavailable={item.kind === '360' ? undefined : 'Only a 360 section can be aimed at a point: a flat camera does not show every direction.'} map={h => <TrackMap folder={folder} tz={tz} span={[item.t0, item.t1]} frames={frames} label={`Street view ${item.label}`} {...h} />} />}
      preview={section ? <><SectionContent folder={folder} tz={tz} section={section} onChoose={choose} onHires={(key, on) => run(() => api.setSvHires(folder, key, on))} showChoice={false} /><div className="mt-2 space-y-0.5"><SectionFacts s={section} tz={tz} by={by} /></div></> : <p className="text-sm text-stone-500">Loading the section…</p>}
      settings={<>
        <div className="flex items-center gap-2"><span className="w-24 text-stone-500">Drawn as</span><span>along the road, with a steady virtual camera</span></div>
        <LengthField id={item.key} mode={item.seconds == null ? '' : 'set'} seconds={item.seconds} modes={['set']} min={item.min_s} max={item.max_s} fallback={item.default_s} onChange={(_, seconds) => run(() => api.setSvLength(folder, item.key, seconds))} />
        <div className="sm:col-span-2"><ChoiceRadios section={section ?? ({ provider: item.provider, id: item.id, key: item.key, choice: item.choice, plausible: true, why_not: '' } as never)} onChoose={choose} /></div>
      </>}
      help={item.seconds != null ? `The film shows this section for exactly this long (it can play ${item.min_s} to ${item.max_s} s); the music fit never changes it.` : `The plan sets the length to fit the music, anywhere from ${item.min_s} to ${item.max_s} s (the same road played faster or slower).`} />
  )
}
