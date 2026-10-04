import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, setup, waitFor } from '../utils/render'
import SvItemPage from '../../src/components/SvItemPage'
import { CamAimPicker, usePointCams } from '../../src/components/PointCams'
import { makePointCam, makePointCams, makeStreetView, makeSvSection } from '../utils/factories'
import { mockGet, recordRequests } from '../utils/api'
import { server } from '../utils/server'
import type { AimPath, PointCamSource, SvChosen } from '../../src/api'

const rel: AimPath = { kind: 'rel', t: [0, 1, 2], yaw: [0, 0, 0], pitch: [0, 0, 0], fov: [40, 40, 40], on: [true, true, true] }

function Picker({ source, onGo }: { source: PointCamSource; onGo?: (id: string) => void }) {
  const pc = usePointCams('/data', source); const [picked, setPicked] = useStateFor()
  return <CamAimPicker pc={pc} picked={picked} onPick={setPicked} onGo={onGo ? c => onGo(c.id) : undefined} note="a note" />
}
import { useState } from 'react'
const useStateFor = () => useState<string | undefined>()

describe('CamAimPicker: choosing which camera to show on the video', () => {
  it('lists the cameras that work, picks one at a time, and goes to its start', async () => {
    mockGet('/api/pointcams', makePointCams([makePointCam({ name: 'the old mill' }), makePointCam({ id: 'C2', label: 'C2' }), makePointCam({ id: 'C3', label: 'C3', ok: false, error: 'no clip', facts: undefined })])); const go = vi.fn()
    const { user } = setup(<Picker source={{ kind: 'clip', clip: 'c1' }} onGo={go} />)
    expect(await screen.findByLabelText('Show C1')).not.toBeChecked(); expect(screen.getByLabelText('No camera')).toBeChecked(); expect(screen.getByText(/C1 · the old mill/)).toBeInTheDocument(); expect(screen.queryByLabelText('Show C3')).toBeNull()      // (one that cannot give its shot is not offered)
    expect(screen.queryByRole('button', { name: /Go to/ })).toBeNull(); await user.click(screen.getByLabelText('Show C2')); expect(screen.getByLabelText('Show C2')).toBeChecked(); expect(screen.getByLabelText('Show C1')).not.toBeChecked(); expect(screen.getByText(/where it aims/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Go to C2' })); expect(go).toHaveBeenCalledWith('C2'); await user.click(screen.getByLabelText('No camera')); expect(screen.queryByRole('button', { name: /Go to/ })).toBeNull(); expect(screen.getByRole('note')).toHaveTextContent('a note')
  })
  it('is not there when the clip has no camera', async () => { mockGet('/api/pointcams', makePointCams([])); setup(<Picker source={{ kind: 'clip', clip: 'c1' }} />); await waitFor(() => expect(screen.queryByRole('group', { name: /Show a point camera/ })).toBeNull()) })
})

describe('the street view page: a camera picked under the video is drawn on it', () => {
  const key = 'mapillary:s1:1.20'
  const item = (): SvChosen => ({ key, label: 'V1', id: 'M1', provider: 'mapillary', kind: '360', choice: 'possible', t0: 1_771_700_000, t1: 1_771_700_300, length_m: 800, quality: 'good', min_s: 4, max_s: 40, seconds: null, default_s: 12, script: [] })
  it('asks for the aim over the flat preview and over the look-around, and says why one cannot be drawn on', async () => {
    const sv = makeStreetView(); sv.sections[0] = makeSvSection({ id: 'M1', key, choice: 'possible', label: 'V1', kind: '360' }); mockGet('/api/streetview', sv); mockGet('/api/pointcams', makePointCams([makePointCam({ source: { kind: 'streetview', key } })]))
    mockGet('/api/streetview/video', { exists: true, running: false, log: [], error: '', seconds: 10, fps: 2, progress: null }); const seen = recordRequests('/api/pointcams/path')
    server.use(http.get('/api/pointcams/path', ({ request }) => new URL(request.url).searchParams.get('view') === 'pano' ? HttpResponse.json({ detail: 'only a 360 section can be looked around in' }, { status: 400 }) : HttpResponse.json({ ...rel, viewer: { yaw: 0, pitch: -2, fov: 85 } })))
    const { user } = setup(<SvItemPage folder="/data" item={item()} tz="UTC" onChanged={() => {}} />); await user.click(await screen.findByLabelText('Show C1'))
    await waitFor(() => expect(seen.map(r => r.url.searchParams.get('view')).sort()).toEqual(['flat', 'pano'])); expect(seen[0].url.searchParams.get('id')).toBe('C1')
    expect(await screen.findByText(/C1 cannot be drawn on this video: only a 360 section/)).toBeInTheDocument(); expect(document.querySelector('[data-aim-overlay]')).not.toBeNull()
    await user.click(screen.getByLabelText('No camera')); await waitFor(() => expect(screen.queryByText(/cannot be drawn on this video/)).toBeNull())
  })
})
