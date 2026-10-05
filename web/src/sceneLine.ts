// One direction's scene labels (the scenes stage's summary.front / summary.rear) as a line for the clip page: what is there, the weather and light, water, snow on the ground and a few tags.
const keys = (o?: Record<string, number> | null) => Object.keys(o ?? {})

/** "forest, trail · fog · overcast · river · snow on the ground · trees, mist" for a summary block; '' when the block has nothing. */
export function sceneLine(b?: { settings?: Record<string, number>; weather?: Record<string, number>; lighting?: Record<string, number>; water?: Record<string, number>; ground_snow?: number | null; tags?: string[] } | null): string {
  if (!b) return ''
  const parts = [keys(b.settings).slice(0, 3).join(', '), keys(b.weather).slice(0, 2).join(', '), keys(b.lighting).slice(0, 2).join(', '), keys(b.water).join(', '), (b.ground_snow ?? 0) >= 0.3 ? `snow on the ground (${Math.round((b.ground_snow ?? 0) * 100)}%)` : '', (b.tags ?? []).slice(0, 5).join(', ')]
  return parts.filter(Boolean).join(' · ')
}
