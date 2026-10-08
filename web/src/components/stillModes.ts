import type { EnlargeMode } from '../api'

// The sizes a still or the film can be made at, and how far the local model enlarges a shot that holds too few pixels (edit/upscale.py): to the output size, or to 1080p / 1440p and then a standard resample.
export const SIZES: [string, string][] = [['1920x1080', '1080p'], ['2560x1440', '1440p'], ['3840x2160', '4K']]
export const sizeLabel = (size: string | [number, number] | null | undefined) => {
  if (!size) return '?'
  const k = Array.isArray(size) ? `${size[0]}x${size[1]}` : size
  return SIZES.find(s => s[0] === k)?.[1] ?? k
}
export const ENLARGE: [EnlargeMode, string][] = [['off', 'No enlarging'], ['1080p', 'Model to 1080p, then resample'], ['1440p', 'Model to 1440p, then resample'], ['full', 'Model to the full output size']]
export const enlargeLabel = (m: EnlargeMode | null | undefined) => m ? ENLARGE.find(e => e[0] === m)?.[1] ?? m : 'unknown'
/** Short form for a caption: "no enlarging", "model to 1080p", "model to full size". */
export const enlargeShort = (m: EnlargeMode | null | undefined) => m == null ? '' : m === 'off' ? 'no enlarging' : m === 'full' ? 'model to full size' : `model to ${m}`
export const clock = (t: number) => { const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(1).padStart(4, '0')}` }
