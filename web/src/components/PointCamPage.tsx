import { useCallback, useState } from 'react'
import { api, type PointCam, type PointCams } from '../api'
import { addPointCams } from '../mapLayers'
import ItemPage from './ItemPage'
import TrackMap from './TrackMap'
import { NameField, PointCamFacts, PointCamLength, PointCamPreview, PointCamSettingsFields, UseRadios } from './PointCams'

// A point camera offered to the film as a page of its own (like a gap, a photo or a street view section): the shot, where the camera looks from and at, its settings, what the script says over it and your notes.
export default function PointCamPage({ folder, cam, limits, tz, onChanged }: { folder: string; cam?: PointCam; limits?: PointCams['limits']; tz: string; onChanged: () => void }) {
  const [err, setErr] = useState<string>()
  const decorate = useCallback((_m: unknown, g: import('leaflet').LayerGroup) => { if (cam) addPointCams(g, [cam], cam.id, () => {}) }, [cam])
  if (!cam) return <p className="text-sm text-stone-500">That point camera is not offered to the film any more.</p>
  const run = async (fn: () => Promise<unknown>) => { setErr(undefined); try { await fn() } catch (e) { setErr((e as Error).message) } onChanged() }
  const set = (f: Parameters<typeof api.updatePointCam>[2]) => run(() => api.updatePointCam(folder, cam.id, f))
  const src = cam.source.kind === 'clip' ? `clip ${cam.source.clip}` : 'a street view section'
  return (
    <ItemPage folder={folder} noun="point camera" must={cam.use === 'must'} script={cam.script} err={err} noteClip={cam.label} noteTitle="Notes for this point camera" notePlaceholder="What is this place? Why does it matter, what to mention or avoid…"
      heading={<>Point camera {cam.label} <span className="text-sm font-normal text-stone-500">{cam.name ? `${cam.name} · ` : ''}from {src}</span></>}
      sub={cam.ok && cam.facts ? `${cam.facts.seconds} s of the run · the point is ${cam.facts.min_dist_m} m from the path at the closest` : undefined}
      where={cam.ok && cam.window ? <TrackMap folder={folder} tz={tz} span={cam.window} label={`Point camera ${cam.label}`} decorate={decorate} /> : undefined}
      preview={<div className="space-y-2"><PointCamFacts cam={cam} />{cam.ok && <PointCamPreview folder={folder} cam={cam} />}</div>}
      settings={<>
        <NameField cam={cam} onChange={name => set({ name })} />
        <PointCamSettingsFields cam={cam} limits={limits} onChange={set} />
        <PointCamLength cam={cam} onChange={seconds => set({ seconds })} />
        <div className="sm:col-span-2"><UseRadios cam={cam} onChange={use => set({ use })} /></div>
      </>}
      help={cam.seconds != null ? `The film shows this shot for exactly this long (it can play ${cam.range?.[0]} to ${cam.range?.[1]} s: a shorter shot is the part nearest the point); the music fit never changes it.` : `The plan sets the length to fit the music, anywhere from ${cam.range?.[0] ?? 2} to ${cam.range?.[1] ?? '?'} s (a shorter shot is the part nearest the point).`} />
  )
}
