import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, setup, waitFor, within } from '../utils/render'
import { PointCamTool, usePointCams } from '../../src/components/PointCams'
import PointCamPage from '../../src/components/PointCamPage'
import { destination } from '../../src/mapLayers'
import Workspace from '../../src/components/Workspace'
import { makeClipInfo, makePointCam, makePointCams, makeTracksListing } from '../utils/factories'
import { mockError, mockGet, mockPost, recordRequests } from '../utils/api'
import { server } from '../utils/server'
import type { PointCam, PointCamSource } from '../../src/api'

const line = { lat: [50.0, 50.01, 50.02], lon: [5.0, 5.01, 5.02], t: [0, 100, 200] }
const clip: PointCamSource = { kind: 'clip', clip: 'CAM_1_0001_D' }

/** The tool with a stand-in for the map: a button that clicks the map at a place, and what the map was told to draw. */
function Harness({ source = clip, unavailable }: { source?: PointCamSource; unavailable?: string }) {
  const pc = usePointCams('/data', source)
  return <PointCamTool folder="/data" source={source} pc={pc} unavailable={unavailable} map={h => <div><button onClick={() => h.onMapClick(50.01, 5.02)}>click the map</button><span data-testid="fit">{h.fitTo?.key ?? 'none'}</span></div>} />
}

const video = (o = {}) => ({ exists: false, running: false, log: [], error: '', progress: null, ...o })

describe('point cameras on a clip or street view page', () => {
  it('has a button that arms the map, and a click on the map makes a camera and disarms it', async () => {
    mockGet('/api/pointcams', makePointCams([])); mockGet('/api/pointcams/video', video()); const made = recordRequests('/api/pointcams')
    mockPost('/api/pointcams', makePointCam({ id: 'C1', label: 'C1' }))
    const { user } = setup(<Harness />); expect(await screen.findByText('No point cameras here yet.')).toBeInTheDocument()
    const arm = screen.getByRole('button', { name: 'Add a point camera' }); expect(arm).toHaveAttribute('aria-pressed', 'false')
    await user.click(screen.getByText('click the map')); expect(made.filter(r => r.method === 'POST')).toHaveLength(0)                                   // not armed: a click only moves the map
    await user.click(arm); expect(screen.getByRole('button', { name: 'Now click the map near the path' })).toHaveAttribute('aria-pressed', 'true')
    mockGet('/api/pointcams', makePointCams([makePointCam()])); await user.click(screen.getByText('click the map'))
    await waitFor(() => expect(made.filter(r => r.method === 'POST')).toHaveLength(1)); expect(made.find(r => r.method === 'POST')!.body).toEqual({ folder: '/data', source: clip, lat: 50.01, lon: 5.02 })
    expect(await screen.findByRole('region', { name: 'Point camera C1' })).toHaveAttribute('data-picked', ''); expect(screen.getByTestId('fit')).toHaveTextContent('C1')                // the new camera is picked and the map moves to it
    expect(screen.getByRole('button', { name: 'Add a point camera' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('says why a click was refused', async () => {
    mockGet('/api/pointcams', makePointCams([])); mockError('/api/pointcams', 400, 'that point is 700 m from the path: click nearer to it (within 400 m)', 'post')
    const { user } = setup(<Harness />); await user.click(await screen.findByRole('button', { name: 'Add a point camera' })); await user.click(screen.getByText('click the map'))
    expect(await screen.findByRole('alert')).toHaveTextContent('700 m from the path'); expect(screen.getByRole('button', { name: 'Add a point camera' })).toBeEnabled()
  })

  it('asks only for the cameras of this clip, and says when the source cannot be aimed at', async () => {
    const seen = recordRequests('/api/pointcams'); mockGet('/api/pointcams', makePointCams([]))
    const { unmount } = setup(<Harness />); await screen.findByText('No point cameras here yet.'); expect(seen[0].url.searchParams.get('clip')).toBe('CAM_1_0001_D'); expect(seen[0].url.searchParams.get('key')).toBeNull(); unmount()
    setup(<Harness source={{ kind: 'streetview', key: 'mapillary:s1:1.2' }} unavailable="Only a 360 section can be aimed at a point" />); await waitFor(() => expect(seen.some(r => r.url.searchParams.get('key') === 'mapillary:s1:1.2')).toBe(true))
    expect(screen.getByText(/Only a 360 section can be aimed/)).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Add a point camera' })).toBeNull()
  })

  it('shows the facts and the warnings of a camera, and why one cannot give its shot', async () => {
    const warn = 'the view swings up to 80 degrees a second where the path passes 3 m from the point: raise the smoothing, or pick a point further from the path'
    mockGet('/api/pointcams', makePointCams([makePointCam({ facts: { ...makePointCam().facts!, warnings: [warn], max_pan_deg_s: 80 } }), makePointCam({ id: 'C2', label: 'C2', ok: false, error: 'no clip CAM_1_0001_D', facts: undefined })])); mockGet('/api/pointcams/video', video())
    setup(<Harness />); const c1 = await screen.findByRole('region', { name: 'Point camera C1' })
    expect(within(c1).getByText(/26.7 s of footage · the point is 30 m from the path at the closest, 62 m at the furthest · the view turns 140° \(up to 80° a second\) · zoom 70° to 95° · plays 2 to 26.7 s in the film/)).toBeInTheDocument(); expect(within(c1).getByRole('note')).toHaveTextContent('raise the smoothing')
    const c2 = screen.getByRole('region', { name: 'Point camera C2' }); expect(within(c2).getByRole('alert')).toHaveTextContent('cannot give its shot: no clip CAM_1_0001_D'); expect(within(c2).queryByRole('button', { name: 'Render a preview' })).toBeNull()
  })

  it('saves what you change: the stretch, the zoom, the height, the smoothing, the name and whether the planner may use it', async () => {
    mockGet('/api/pointcams', makePointCams([makePointCam()])); mockGet('/api/pointcams/video', video()); const upd = recordRequests('/api/pointcams/update'); mockPost('/api/pointcams/update', makePointCam())
    const { user } = setup(<Harness />); const c = within(await screen.findByRole('region', { name: 'Point camera C1' }))
    const set = async (label: string, v: string) => { const f = c.getByLabelText(label); await user.clear(f); await user.type(f, v); await user.tab() }
    await set('Metres of path before', '70'); await set('Metres of path after', '25'); await set('Zoom close to the point', '100'); await set('Zoom far from the point', '45'); await set('Height of the point', '30'); await set('Smoothing of the pan', '1.5')
    await user.type(c.getByLabelText('What it looks at'), 'the old mill'); await user.tab(); await user.click(c.getByLabelText('Must include'))
    await waitFor(() => expect(upd).toHaveLength(8)); expect(upd.map(r => r.body)).toEqual([{ folder: '/data', id: 'C1', before_m: 70 }, { folder: '/data', id: 'C1', after_m: 25 }, { folder: '/data', id: 'C1', fov_near: 100 }, { folder: '/data', id: 'C1', fov_far: 45 }, { folder: '/data', id: 'C1', height_m: 30 }, { folder: '/data', id: 'C1', smooth_s: 1.5 }, { folder: '/data', id: 'C1', name: 'the old mill' }, { folder: '/data', id: 'C1', use: 'must' }])
    expect(c.getByLabelText('Not used')).toBeChecked()                                                                         // (the page shows what the server says: nothing changed in this fake)
  })

  it('removes a camera after asking', async () => {
    mockGet('/api/pointcams', makePointCams([makePointCam()])); mockGet('/api/pointcams/video', video()); const del = recordRequests('/api/pointcams/delete'); mockPost('/api/pointcams/delete', { removed: true })
    const { user } = setup(<Harness />); const c = within(await screen.findByRole('region', { name: 'Point camera C1' })); const ask = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    await user.click(c.getByRole('button', { name: 'Remove' })); expect(del).toHaveLength(0); await user.click(c.getByRole('button', { name: 'Remove' })); await waitFor(() => expect(del).toHaveLength(1)); expect(del[0].body).toEqual({ folder: '/data', id: 'C1' }); ask.mockRestore()
  })

  it('renders a preview on demand with a progress bar and a log, then plays it', async () => {
    mockGet('/api/pointcams', makePointCams([makePointCam()])); let state = video(); server.use(http.get('/api/pointcams/video', () => HttpResponse.json(state)))
    const start = recordRequests('/api/pointcams/video'); server.use(http.post('/api/pointcams/video', () => { state = video({ running: true, log: ['rendering 5 of 20 frames'], progress: { pct: 25, phase: 'rendering the video', done: 5, total: 20 } }); return HttpResponse.json({ started: true }) }))
    const { user } = setup(<Harness />); await user.click(await screen.findByRole('button', { name: 'Render a preview' }))
    const bar = await screen.findByRole('progressbar', { name: 'Progress' }); expect(bar).toHaveAttribute('aria-valuenow', '25'); expect(screen.getByText('rendering the video: 5 of 20')).toBeInTheDocument(); expect(screen.getByRole('list', { name: 'What it is doing' })).toHaveTextContent('rendering 5 of 20 frames')
    expect(start.filter(r => r.method === 'POST')[0].body).toEqual({ folder: '/data', id: 'C1' })
    state = video({ exists: true }); const v = await screen.findByLabelText('Preview video of C1', undefined, { timeout: 4000 }); expect(v).toHaveAttribute('src', expect.stringContaining('/api/pointcams/video/file?')); expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('shows why a preview failed', async () => {
    mockGet('/api/pointcams', makePointCams([makePointCam()])); mockGet('/api/pointcams/video', video({ error: 'pointcam-video: clip c1 has no proxy yet' })); setup(<Harness />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no proxy yet'); expect(screen.getByRole('button', { name: 'Render a preview' })).toBeInTheDocument()
  })
})

describe('the page of a point camera in the film', () => {
  const page = (cam?: PointCam, onChanged = () => {}) => setup(<PointCamPage folder="/data" cam={cam} limits={makePointCams().limits} tz="UTC" onChanged={onChanged} />)
  const mapData = () => { mockGet('/api/track/line', line); mockGet('/api/tracks', makeTracksListing()); mockGet('/api/pointcams/video', video()) }

  it('has the sections of every film item, with the camera on the map and its shot', async () => {
    mapData(); page(makePointCam({ use: 'must', name: 'the old mill', script: [{ n: 3, type: 'camera', text: 'We pass the old mill.', seconds: 6, kind: null }] }))
    for (const t of ['Preview', 'Where on the route', 'How it is drawn and how long it is', 'Voice-over']) expect(await screen.findByText(t)).toBeInTheDocument()
    expect(screen.getByText('Point camera C1')).toBeInTheDocument(); expect(screen.getByText(/the old mill · from clip CAM_1_0001_D/)).toBeInTheDocument(); expect(screen.getByText('We pass the old mill.')).toBeInTheDocument(); expect(screen.getByText('Notes for this point camera')).toBeInTheDocument()
    await waitFor(() => expect(document.querySelector('[data-pointcam-marker="C1"]')).not.toBeNull())                          // the bullseye on the map
    expect(screen.getByLabelText('Must include')).toBeChecked(); expect(screen.getByLabelText('Length')).toHaveValue(''); expect(screen.getByText(/anywhere from 2 to 26.7 s/)).toBeInTheDocument()
  })

  it('saves an exact length and the choice, and tells the film list', async () => {
    mapData(); const upd = recordRequests('/api/pointcams/update'); mockPost('/api/pointcams/update', makePointCam()); const changed = vi.fn(); const { user } = page(makePointCam(), changed)
    await user.selectOptions(await screen.findByLabelText('Length'), 'set'); await waitFor(() => expect(upd).toHaveLength(1)); expect(upd[0].body).toEqual({ folder: '/data', id: 'C1', seconds: 26.7 })          // (the whole shot, to start from)
    await user.click(screen.getByLabelText('Possible')); await waitFor(() => expect(upd).toHaveLength(2)); expect(upd[1].body).toEqual({ folder: '/data', id: 'C1', use: 'possible' }); expect(changed).toHaveBeenCalledTimes(2)
  })

  it('says so when the camera is not offered any more, and when its source cannot give the shot', async () => {
    const { unmount } = page(undefined); expect(screen.getByText(/not offered to the film any more/)).toBeInTheDocument(); unmount()
    mapData(); page(makePointCam({ ok: false, error: 'no clip CAM_1_0001_D', facts: undefined, window: undefined })); expect(await screen.findByRole('alert')).toHaveTextContent('no clip CAM_1_0001_D'); expect(screen.queryByText('Where on the route')).toBeNull()
  })

  it('sits among the clips in the film list and opens from there', async () => {
    mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_1_0001_D', start_utc: '2026-02-20T10:00:00Z' })] }); mapData()
    mockGet('/api/pointcams', makePointCams([makePointCam({ use: 'must', name: 'the old mill' }), makePointCam({ id: 'C2', label: 'C2', use: '' })]))
    const { user } = setup(<Workspace folder="/data" onChange={() => {}} />); const row = await screen.findByText('Point camera · the old mill'); expect(row.closest('li')).toHaveAttribute('data-cam-row', 'C1'); expect(screen.getByText(/26.7 s · clip · must use/)).toBeInTheDocument()
    expect(document.querySelector('[data-cam-row="C2"]')).toBeNull()                                                            // (not offered: not in the list)
    await user.click(row); expect(await screen.findByText(/the old mill · from clip/)).toBeInTheDocument(); expect(screen.getByText('How it is drawn and how long it is')).toBeInTheDocument()
  })
})

describe('the camera on the map', () => {
  it('works out the place a view reaches from the compass bearing and the distance', () => {
    const north = destination(50, 5, 0, 111320), east = destination(50, 5, 90, 111320 * Math.cos((50 * Math.PI) / 180)), back = destination(50, 5, 180, 1000)
    expect(north[0]).toBeCloseTo(51, 5); expect(north[1]).toBeCloseTo(5, 5); expect(east[0]).toBeCloseTo(50, 5); expect(east[1]).toBeCloseTo(6, 5); expect(back[0]).toBeLessThan(50); expect(back[1]).toBeCloseTo(5, 6)
  })
})
