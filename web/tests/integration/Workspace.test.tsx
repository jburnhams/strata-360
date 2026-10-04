import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import Workspace from '../../src/components/Workspace'
import { screen, setup, waitFor } from '../utils/render'
import { makeMeta, makeClipInfo, makeGap, makeGapClip, makePhoto } from '../utils/factories'
import { mockGet, mockError } from '../utils/api'

// Mock the many child panels that are tested in their own files
vi.mock('../../src/components/FilmDetails', () => ({ default: () => <div data-testid="FilmDetails" /> }))
vi.mock('../../src/components/ProjectProgress', () => ({ default: ({ onResults }: any) => <div data-testid="ProjectProgress"><button onClick={onResults}>Go to results</button></div> }))
vi.mock('../../src/components/TrackPanel', () => ({ default: () => <div data-testid="TrackPanel" /> }))
vi.mock('../../src/components/ClockPanel', () => ({ default: () => <div data-testid="ClockPanel" /> }))
vi.mock('../../src/components/WhoPanel', () => ({ default: () => <div data-testid="WhoPanel" /> }))
vi.mock('../../src/components/NoteBox', () => ({ default: () => <div data-testid="NoteBox" /> }))
vi.mock('../../src/components/ScriptPanel', () => ({ default: ({ onOpen }: any) => <div data-testid="ScriptPanel"><button onClick={() => onOpen('CAM_123')}>Open</button></div> }))
vi.mock('../../src/components/VoiceoverPanel', () => ({ default: () => <div data-testid="VoiceoverPanel" /> }))
vi.mock('../../src/components/TranscriptPanel', () => ({ default: ({ onOpen }: any) => <div data-testid="TranscriptPanel"><button onClick={() => onOpen('CAM_123', 0)}>Open</button></div> }))
vi.mock('../../src/components/Timeline', () => ({ default: ({ onOpenClip }: any) => <div data-testid="Timeline"><button onClick={() => onOpenClip('CAM_123')}>Open</button></div> }))
vi.mock('../../src/components/PhotosPanel', () => ({ default: ({ photos }: any) => <div data-testid="PhotosPanel">{(photos ?? []).length}</div> }))
vi.mock('../../src/components/GapView', () => ({ default: ({ gap }: { gap: string }) => <div data-testid="GapView">{gap}</div> }))
vi.mock('../../src/components/ClipView', () => ({ default: ({ clip }: { clip: string }) => <div data-testid="ClipView">{clip}</div> }))

// We need fake timers since it polls api.clips and api.meta
beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })



describe('Workspace', () => {
  it('renders the overview and polls for meta and clips', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_123', duration_s: 20 })] })
    mockGet('/api/meta', makeMeta())

    setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)

    // Header folder path
    expect(await screen.findByText('/data/myfolder')).toBeInTheDocument()

    // Sub-components of the overview
    expect(screen.getByTestId('FilmDetails')).toBeInTheDocument()
    expect(screen.getByTestId('ProjectProgress')).toBeInTheDocument()

    // Clip rendered in sidebar
    expect(await screen.findByText(/20 s/)).toBeInTheDocument()
  })


  it('shows an empty state when clips load without items', async () => {
    mockGet('/api/clips', { clips: undefined }) // trigger loading/empty logic
    mockGet('/api/meta', makeMeta())
    setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)
    expect(await screen.findByText('/data/myfolder')).toBeInTheDocument()
  })


  it('navigates back to the overview when Overview button is clicked', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_123', duration_s: 20 })] })
    mockGet('/api/meta', makeMeta())
    const { user } = setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)
    const clipRow = await screen.findByText(/20 s/)
    await user.click(clipRow)
    expect(screen.queryByTestId('FilmDetails')).not.toBeInTheDocument()

    // click overview
    await user.click(screen.getByRole('button', { name: 'Overview' }))
    expect(screen.getByTestId('FilmDetails')).toBeInTheDocument()
  })



  it('passes onOpen callbacks from sub-components', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_123', duration_s: 20 })] })
    mockGet('/api/meta', makeMeta())

    const { user } = setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)
    await screen.findByTestId('ScriptPanel')

    // test script panel
    await user.click(screen.getByTestId('ScriptPanel').querySelector('button')!)
    expect(screen.getByTestId('ClipView')).toHaveTextContent('CAM_123')
    await user.click(screen.getByRole('button', { name: 'Overview' }))

    // test transcript panel
    await user.click(screen.getByTestId('TranscriptPanel').querySelector('button')!)
    expect(screen.getByTestId('ClipView')).toHaveTextContent('CAM_123')
    await user.click(screen.getByRole('button', { name: 'Overview' }))

    // test timeline
    await user.click(screen.getByRole('button', { name: 'Timeline' }))
    await user.click(screen.getByTestId('Timeline').querySelector('button')!)
    expect(screen.getByTestId('ClipView')).toHaveTextContent('CAM_123')
  })




  it('selects a clip, hiding the overview and showing ClipView', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_123', duration_s: 20 })] })
    mockGet('/api/meta', makeMeta())

    const { user } = setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)

    // Wait for clips list
    const clipRow = await screen.findByText(/20 s/)

    // Overview visible initially
    expect(screen.queryByTestId('FilmDetails')).toBeInTheDocument()

    // Click clip
    await user.click(clipRow)

    // ClipView is shown instead
    expect(screen.queryByTestId('FilmDetails')).not.toBeInTheDocument()
    expect(screen.getByTestId('ClipView')).toHaveTextContent('CAM_123')
  })

  it('the progress panel\'s results button opens the timeline (film preview and final render)', async () => {
    const { user } = setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Go to results' }))
    expect(await screen.findByTestId('Timeline')).toBeInTheDocument()
  })

  it('transitions to timeline view when Timeline button is clicked', async () => {
    mockGet('/api/clips', { clips: [] })
    const { user } = setup(<Workspace folder="/data/myfolder" onChange={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'Timeline' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Timeline' }))

    // Timeline component rendered
    expect(screen.getByTestId('Timeline')).toBeInTheDocument()
    expect(screen.queryByTestId('FilmDetails')).not.toBeInTheDocument()
  })

  it('calls onChange when "open another / new project" is clicked', async () => {
    const onChange = vi.fn()
    const { user } = setup(<Workspace folder="/data/myfolder" onChange={onChange} />)

    await user.click(await screen.findByRole('button', { name: 'open another / new project' }))
    expect(onChange).toHaveBeenCalled()
  })

  it('lists the gaps among the clips in time order and opens a gap page when one is clicked', async () => {
    mockGet('/api/meta', makeMeta()); mockGet('/api/clips', { clips: [makeClipInfo()] })
    mockGet('/api/gaps', { gaps: [makeGap({ settings: { kind: null, mode: null, seconds: null, must: true }, clips: [makeGapClip({ exists: true, kind: 'flyover', seconds: 12 })] }), makeGap({ id: 'G02', local_start: 'Fri 20 Feb 06:00' })] })
    const { user } = setup(<Workspace folder="/data" onChange={() => {}} />)
    expect(await screen.findByText('G02')).toBeInTheDocument(); expect(screen.getByText(/3D · 12 s · must use/)).toBeInTheDocument(); expect(screen.getByText(/no clip/)).toBeInTheDocument()
    await user.click(screen.getByText('G02')); expect(await screen.findByTestId('GapView')).toHaveTextContent('G02'); expect(screen.queryByTestId('FilmDetails')).not.toBeInTheDocument()
  })
})


describe('the clip and gap list highlights', () => {
  it('puts a green border on the clips and gaps the film uses and a yellow highlight on the one you are looking at', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_20260222100100_0001_D', in_film: true }), makeClipInfo({ id: 'CAM_20260222100200_0002_D', in_film: false })] })
    mockGet('/api/gaps', { gaps: [makeGap({ id: 'G01', in_film: true }), makeGap({ id: 'G02', in_film: false })] }); mockGet('/api/meta', makeMeta())
    const { user } = setup(<Workspace folder="/data/f" onChange={vi.fn()} />)
    const rows = async () => { await screen.findByText('/data/f'); await waitFor(() => expect(document.querySelectorAll('li[data-in-film], li.cursor-pointer').length).toBeGreaterThan(3)); return [...document.querySelectorAll('li.cursor-pointer')] as HTMLElement[] }
    const r = await rows(); const clipA = r[0], clipB = r[1], gapA = r[2], gapB = r[3]
    expect(clipA).toHaveAttribute('data-in-film'); expect(clipA.className).toContain('border-emerald-600'); expect(clipB).not.toHaveAttribute('data-in-film'); expect(clipB.className).toContain('border-transparent')
    expect(gapA).toHaveAttribute('data-in-film'); expect(gapA.className).toContain('border-emerald-600'); expect(gapB.className).toContain('border-transparent')
    expect([clipA, clipB, gapA, gapB].some(e => e.hasAttribute('data-selected'))).toBe(false)
    await user.click(clipB); expect(clipB).toHaveAttribute('data-selected'); expect(clipB.className).toContain('bg-yellow-100'); expect(clipB.className).not.toContain('emerald'); expect(clipA).not.toHaveAttribute('data-selected')
    await user.click(clipA); expect(clipA.className).toContain('bg-yellow-100'); expect(clipA.className).toContain('border-emerald-600')                       // used in the film and selected: both show
    await user.click(gapB); expect(gapB).toHaveAttribute('data-selected'); expect(gapB.className).toContain('bg-yellow-100'); expect(gapB.className).not.toContain('bg-emerald-100'); expect(clipA).not.toHaveAttribute('data-selected')
  })
})

describe('one list of everything the film can use, in time order', () => {
  it('puts the gaps, the photos and the street view ticked for the film among the clips by time', async () => {
    const t = (iso: string) => Date.parse(iso) / 1000
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_1_0001_D', start_utc: '2026-02-20T10:00:00Z' }), makeClipInfo({ id: 'CAM_2_0002_D', start_utc: '2026-02-20T16:00:00Z' })] })
    mockGet('/api/gaps', { gaps: [makeGap({ id: 'G01', t0: t('2026-02-20T11:00:00Z'), t1: t('2026-02-20T15:00:00Z') })] })
    mockGet('/api/photos', { photos: [makePhoto({ id: 'p1', use: true, taken_utc: t('2026-02-20T12:00:00Z') }), makePhoto({ id: 'p2', taken_utc: t('2026-02-20T12:30:00Z') })], tz: 'UTC' })
    mockGet('/api/streetview/chosen', { sections: [{ key: 'mapillary:s:3.00', label: 'V1', id: 'M3', provider: 'mapillary', kind: '360', choice: 'must', t0: t('2026-02-20T13:00:00Z'), t1: t('2026-02-20T13:05:00Z'), length_m: 800, quality: 'good' }] })
    setup(<Workspace folder="/data" onChange={() => {}} />)
    await screen.findByText('V1')
    const order = Array.from(document.querySelectorAll('aside li')).map(li => li.textContent ?? '')
    expect(order.findIndex(x => x.includes('0001'))).toBeLessThan(order.findIndex(x => x.includes('G01'))); expect(order.findIndex(x => x.includes('G01'))).toBeLessThan(order.findIndex(x => x.includes('Photo P1')))
    expect(order.findIndex(x => x.includes('Photo P1'))).toBeLessThan(order.findIndex(x => x.includes('V1'))); expect(order.findIndex(x => x.includes('V1'))).toBeLessThan(order.findIndex(x => x.includes('0002')))
    expect(order.some(x => x.includes('Photo P2'))).toBe(false)
  })

  it('puts a gap after the photo it starts at (the final gap starts at the last photo)', async () => {
    const t = Date.parse('2026-02-20T12:00:00Z') / 1000
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_1_0001_D', start_utc: '2026-02-20T10:00:00Z' })] })
    mockGet('/api/gaps', { gaps: [makeGap({ id: 'G21', t0: t, t1: t + 700 })] }); mockGet('/api/photos', { photos: [makePhoto({ id: 'p2', use: true, taken_utc: t })], tz: 'UTC' })
    setup(<Workspace folder="/data" onChange={() => {}} />); await screen.findByText('G21')
    const order = Array.from(document.querySelectorAll('aside li')).map(li => li.textContent ?? ''); expect(order.findIndex(x => x.includes('Photo P2'))).toBeLessThan(order.findIndex(x => x.includes('G21')))
  })

  it('shows a picture for a street view section and for a gap whose clip is made, and a label box for one that is not', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_1_0001_D', start_utc: '2026-02-20T10:00:00Z' })] })
    mockGet('/api/gaps', { gaps: [makeGap({ id: 'G01', t0: Date.parse('2026-02-20T11:00:00Z') / 1000, clips: [makeGapClip({ id: 'G01', exists: true, seconds: 12 })] }), makeGap({ id: 'G02', t0: Date.parse('2026-02-20T14:00:00Z') / 1000 })] })
    mockGet('/api/streetview/chosen', { sections: [{ key: 'mapillary:s:3.00', label: 'V1', id: 'M3', provider: 'mapillary', kind: '360', choice: 'must', t0: Date.parse('2026-02-20T13:00:00Z') / 1000, t1: Date.parse('2026-02-20T13:05:00Z') / 1000, length_m: 800, quality: 'good', min_s: 4, max_s: 40, seconds: null, default_s: 12, script: [] }] })
    setup(<Workspace folder="/data" onChange={() => {}} />); await screen.findByText('V1')
    const img = (t: string) => Array.from(document.querySelectorAll('aside li')).find(li => li.textContent?.includes(t))?.querySelector('img')?.getAttribute('src')
    expect(img('G01')).toContain('/api/gaps/thumb?folder=%2Fdata&id=G01'); expect(img('V1')).toContain('/api/streetview/thumb?folder=%2Fdata&key=mapillary%3As%3A3.00'); expect(img('G02')).toBeUndefined()
  })
})
