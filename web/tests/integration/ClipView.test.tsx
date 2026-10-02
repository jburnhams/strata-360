import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setup, screen, waitFor } from '../utils/render'
import ClipView from '../../src/components/ClipView'
import { mockGet, mockError } from '../utils/api'
import { makeClipDetail } from '../utils/factories'

vi.mock('../../src/components/ClipPlayer', () => ({ default: () => <div data-testid="ClipPlayer" /> }))
vi.mock('../../src/components/Moments', () => ({ default: () => <div data-testid="Moments" /> }))
vi.mock('../../src/components/NoteBox', () => ({ default: () => <div data-testid="NoteBox" /> }))
vi.mock('../../src/components/RedoDialog', () => ({ default: () => <div data-testid="RedoDialog" /> }))
vi.mock('../../src/components/Phrase', () => ({ default: () => <div data-testid="Phrase" /> }))
vi.mock('../../src/components/PlayIcons', () => ({ default: () => <div data-testid="PlayIcons" /> }))

describe('ClipView', () => {
  const scrollIntoViewMock = vi.fn()
  beforeEach(() => {
    scrollIntoViewMock.mockClear()
    window.HTMLElement.prototype.scrollIntoView = scrollIntoViewMock
  })

  it('handles initial loading state', () => {
    mockGet('/api/clip', async () => new Promise(() => {}))
    setup(<ClipView folder="/data" clip="CAM_1" />)
    expect(screen.getByLabelText('Loading When and where')).toBeInTheDocument()
  })

  it('displays clip details correctly', async () => {
    mockGet('/api/clip', () => makeClipDetail({
      time: { start_utc: '2023-01-01T12:00:00Z', utc_status: 'verified' },
      video: { source_frames: 300, nominal_fps: 30, dropped_frames: 0 },
      motion: { steady: 0.95, median_shake_dps: 1.2, total_turn_deg: 90, cadence_hz: null },
      places: {
        covered: true,
        summary: { text: 'In a nice place', places: [] },
        points: [{
          label: 'p1', lat: 10, lon: 20,
          address: { display_name: 'Place' },
          nearby: []
        }]
      }
    }))
    setup(<ClipView folder="/data" clip="CAM_1" />)
    expect(await screen.findByText('2023-01-01 12:00:00')).toBeInTheDocument()
  })

  it('shows error states from fetch', async () => {
    mockError('/api/clip', 500, 'Internal Server Error')
    setup(<ClipView folder="/data" clip="CAM_1" />)
    expect(await screen.findByText('Internal Server Error')).toBeInTheDocument()
  })

  it('focuses correctly using scrollIntoView', async () => {
    mockGet('/api/clip', () => makeClipDetail({
      transcript: [{ si: 1, words: [], t0: 1.5, t1: 2.0, lang: 'en', text: 'Hello', text_en: null, flagged: false, who: null }]
    }))
    setup(<ClipView folder="/data" clip="CAM_1" focus={1.5} />)

    await screen.findByTestId('Phrase')
    await waitFor(() => {
      expect(scrollIntoViewMock).toHaveBeenCalledWith({ block: 'center' })
    })
  })
})
