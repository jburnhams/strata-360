import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import PhotoMotion from '../../src/components/PhotoMotion'
import { screen, setup, waitFor } from '../utils/render'
import { makePhoto } from '../utils/factories'
import { mockGet, mockPost, mockError, recordRequests } from '../utils/api'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

const plan = (o = {}) => ({ style: 'push_in', duration_s: 6, zmax: 1.82, seed: 0, subjects: [{ cx: 0.3, cy: 0.3, w: 0.1, h: 0.1, weight: 1, label: 'you' }, { cx: 0.7, cy: 0.6, w: 0.1, h: 0.1, weight: 0.6, label: 'person' }],
  windows: [[0, 0.1, 1, 0.75], [0.2, 0.15, 0.5, 0.4]], size: [4000, 3000], settings: { style: 'auto', seconds: null, seed: 0 }, ...o })

describe('PhotoMotion', () => {
  it('is closed until asked, and says what is saved when something is', () => {
    const { rerender } = setup(<PhotoMotion folder="/data" p={makePhoto()} onChanged={() => {}} />); expect(screen.getByRole('button', { name: 'Pan & zoom' })).toHaveAttribute('aria-expanded', 'false')
    rerender(<PhotoMotion folder="/data" p={makePhoto({ motion: { style: 'pull_out', seconds: 8, seed: 2 } })} onChanged={() => {}} />); expect(screen.getByRole('button', { name: 'Pan & zoom: pull out, 8 s' })).toBeInTheDocument()
    rerender(<PhotoMotion folder="/data" p={makePhoto({ motion: { style: 'auto', seconds: null, seed: 0 } })} onChanged={() => {}} />); expect(screen.getByRole('button', { name: 'Pan & zoom: auto, auto length' })).toBeInTheDocument()
  })

  it('shows the planned move on the picture: the two windows and the path, and what it is aimed at', async () => {
    mockGet('/api/photos/motion', plan()); const { user } = setup(<PhotoMotion folder="/data" p={makePhoto()} onChanged={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'Pan & zoom' })); expect(await screen.findByText(/push in · from the green window to the red one · zoom up to 1.82x · aimed at you, person/)).toBeInTheDocument()
    const svg = screen.getByLabelText('Path of the move'); expect(svg.querySelectorAll('rect')).toHaveLength(2); expect(svg.querySelector('rect')!.getAttribute('stroke')).toBe('#22c55e'); expect(svg.querySelector('line')).not.toBeNull()
  })

  it('asks for another plan when the move, the length or the take is changed, and watches the move', async () => {
    const seen = recordRequests('/api/photos/motion'); mockGet('/api/photos/motion', plan({ style: 'drift' })); const { user } = setup(<PhotoMotion folder="/data" p={makePhoto()} onChanged={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'Pan & zoom' })); await screen.findByText(/aimed at/)
    await user.selectOptions(screen.getByLabelText('Move for IMG_0001.jpg'), 'drift'); await waitFor(() => expect(seen.at(-1)?.url.searchParams.get('style')).toBe('drift'))
    await user.click(screen.getByRole('button', { name: 'Another take for IMG_0001.jpg' })); await waitFor(() => expect(seen.at(-1)?.url.searchParams.get('seed')).toBe('1'))
    const sec = screen.getByLabelText('Seconds for IMG_0001.jpg'); expect(sec).toHaveValue(null); expect(screen.getByText(/\(auto: 6 s\)/)).toBeInTheDocument(); await user.type(sec, '4'); await waitFor(() => expect(seen.at(-1)?.url.searchParams.get('seconds')).toBe('4'))
    await user.clear(sec); await waitFor(() => expect(seen.at(-1)?.url.searchParams.has('seconds')).toBe(false))                     // empty: back to the length that follows the photo
    await user.type(sec, '3.5'); await waitFor(() => expect(seen.at(-1)?.url.searchParams.get('seconds')).toBe('3.5'))
    await user.click(screen.getByRole('button', { name: 'Watch' })); const v = document.querySelector('video')!; expect(v.getAttribute('src')).toContain('/api/photos/motion/video?'); expect(v.getAttribute('src')).toContain('style=drift'); expect(v.getAttribute('src')).toContain('seconds=6')
    await user.click(screen.getByRole('button', { name: 'Hide' })); expect(document.querySelector('video')).toBeNull()
  })

  it('keeps the move when asked, and only offers to when something has changed', async () => {
    const saved = recordRequests('/api/photos/motion'); mockGet('/api/photos/motion', plan()); mockPost('/api/photos/motion', plan({ settings: { style: 'pan', seconds: 6, seed: 0 } })); const changed = vi.fn()
    const { user } = setup(<PhotoMotion folder="/data" p={makePhoto()} onChanged={changed} />)
    await user.click(screen.getByRole('button', { name: 'Pan & zoom' })); const use = await screen.findByRole('button', { name: 'Use this move' }); expect(use).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Move for IMG_0001.jpg'), 'pan'); await waitFor(() => expect(use).toBeEnabled()); await user.click(use)
    await waitFor(() => expect(changed).toHaveBeenCalled()); expect(saved.filter(r => r.method === 'POST').at(-1)?.body).toMatchObject({ folder: '/data', id: 'p1', style: 'pan', seconds: null, seed: 0 })
  })

  it('says why a move cannot be planned', async () => {
    mockError('/api/photos/motion', 400, 'style: auto or one of push_in'); const { user } = setup(<PhotoMotion folder="/data" p={makePhoto()} onChanged={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'Pan & zoom' })); expect(await screen.findByRole('alert')).toHaveTextContent('style: auto or one of push_in')
  })
})
