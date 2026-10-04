import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, setup, waitFor, within } from '../utils/render'
import SvItemPage from '../../src/components/SvItemPage'
import Workspace from '../../src/components/Workspace'
import { makeClipInfo, makeStreetView, makeSvSection } from '../utils/factories'
import { mockGet, recordRequests } from '../utils/api'
import { server } from '../utils/server'
import type { SvChosen } from '../../src/api'

const item = (o: Partial<SvChosen> = {}): SvChosen => ({ key: 'mapillary:s1:1.20', label: 'V1', id: 'M1', provider: 'mapillary', kind: '360', choice: 'possible', t0: 1_771_700_000, t1: 1_771_700_300, length_m: 800, quality: 'good', min_s: 4, max_s: 40, seconds: null, default_s: 12, script: [], ...o })
const sv = () => { const d = makeStreetView(); d.sections[0] = makeSvSection({ id: 'M1', key: 'mapillary:s1:1.20', choice: 'possible', label: 'V1' }); return d }

describe('SvItemPage', () => {
  it('has the sections of a gap and the content of the street view page, with the choice', async () => {
    mockGet('/api/streetview', sv()); setup(<SvItemPage folder="/data" item={item({ script: [{ n: 3, type: 'streetview', text: '', seconds: 6, kind: null }] })} tz="UTC" onChanged={() => {}} />)
    for (const t of ['Preview', 'How it is drawn and how long it is', 'Voice-over']) expect(await screen.findByText(t)).toBeInTheDocument()
    expect(screen.getByText('Street view V1')).toBeInTheDocument(); expect((await screen.findAllByText(/Filmed/)).length).toBeGreaterThan(0); expect(screen.getByText('Notes for this street view section')).toBeInTheDocument(); expect(screen.getByText('picture only')).toBeInTheDocument()
    const group = screen.getByRole('group', { name: /in the film \(details\)/ }); expect(within(group).getByLabelText('Possible')).toBeChecked(); expect(within(group).getByLabelText('Not used')).not.toBeChecked(); expect(within(group).getByLabelText('Must include')).not.toBeChecked()
    expect(screen.getByLabelText('Length')).toHaveValue(''); expect(screen.getByLabelText('Length in seconds')).toBeDisabled()
  })

  it('saves the choice and an exact length', async () => {
    mockGet('/api/streetview', sv()); const ch = recordRequests('/api/streetview/choice'); const len = recordRequests('/api/streetview/length')
    server.use(http.post('/api/streetview/choice', () => HttpResponse.json({ key: 'k', choice: 'must' })), http.post('/api/streetview/length', () => HttpResponse.json({ key: 'k', seconds: 12 })))
    const { user } = setup(<SvItemPage folder="/data" item={item()} tz="UTC" onChanged={() => {}} />)
    await user.click(await screen.findByLabelText('Must include')); await waitFor(() => expect(ch.filter(r => r.method === 'POST')).toHaveLength(1)); expect(ch[0].body).toMatchObject({ key: 'mapillary:s1:1.20', choice: 'must' })
    await user.selectOptions(screen.getByLabelText('Length'), 'set'); await waitFor(() => expect(len.filter(r => r.method === 'POST')).toHaveLength(1)); expect(len[0].body).toMatchObject({ key: 'mapillary:s1:1.20', seconds: 12 })
  })

  it('says so when the section is not chosen any more, and opens from the film list', async () => {
    const { unmount } = setup(<SvItemPage folder="/data" item={undefined} tz="UTC" onChanged={() => {}} />); expect(screen.getByText(/not chosen for the film any more/)).toBeInTheDocument(); unmount()
    mockGet('/api/streetview', sv()); mockGet('/api/clips', { clips: [makeClipInfo({ id: 'CAM_1_0001_D', start_utc: '2026-02-20T10:00:00Z' })] }); mockGet('/api/streetview/chosen', { sections: [item()] })
    const { user } = setup(<Workspace folder="/data" onChange={() => {}} />); await user.click(await screen.findByText('V1')); expect(await screen.findByText('Street view V1')).toBeInTheDocument(); expect(screen.getByText('How it is drawn and how long it is')).toBeInTheDocument()
  })

  it('marks every picture of the section on the map where it was taken, joined by a path', async () => {
    mockGet('/api/streetview', sv()); setup(<SvItemPage folder="/data" item={item()} tz="UTC" onChanged={() => {}} />)
    expect(await screen.findByText(/each picture where it was taken \(\d+\), joined in order/)).toBeInTheDocument()
  })
})
