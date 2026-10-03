import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, setup, waitFor } from '../utils/render'
import PhotoPage from '../../src/components/PhotoPage'
import { makePhoto } from '../utils/factories'
import { recordRequests } from '../utils/api'
import { server } from '../utils/server'

describe('PhotoPage', () => {
  it('has the sections of a gap: how it is drawn, how long, must be used, the voice-over and the notes', () => {
    setup(<PhotoPage folder="/data" photo={makePhoto({ use: true })} tz="UTC" onChanged={() => {}} />)
    for (const t of ['Preview', 'How it is drawn and how long it is', 'Voice-over']) expect(screen.getByText(t)).toBeInTheDocument()
    expect(screen.getByLabelText('Drawn as')).toHaveValue(''); expect(screen.getByLabelText('Length')).toHaveValue(''); expect(screen.getByLabelText('Length in seconds')).toBeDisabled()
    expect(screen.getByLabelText('Must be used in the film')).not.toBeChecked(); expect(screen.getByText(/does not use this photo/)).toBeInTheDocument(); expect(screen.getByText('Notes for this photo')).toBeInTheDocument()
  })

  it('saves the move, the exact length and the must, and lists what the script says over it', async () => {
    const motion = recordRequests('/api/photos/motion'); server.use(http.post('/api/photos/motion', () => HttpResponse.json({ style: 'pan', seconds: 2.5, seed: 0 })))
    const st = recordRequests('/api/photos/settings'); server.use(http.post('/api/photos/settings', () => HttpResponse.json({ id: 'p1', use: true, must: true })))
    const { user } = setup(<PhotoPage folder="/data" photo={makePhoto({ use: true, script: [{ n: 4, type: 'photo', text: 'The view from the col', seconds: 3, kind: null }] })} tz="UTC" onChanged={() => {}} />)
    expect(screen.getByText('The view from the col')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Drawn as'), 'pan'); await waitFor(() => expect(motion.filter(r => r.method === 'POST').at(-1)?.body).toMatchObject({ id: 'p1', style: 'pan' }))
    await user.selectOptions(screen.getByLabelText('Length'), 'set'); await waitFor(() => expect(motion.filter(r => r.method === 'POST').at(-1)?.body).toMatchObject({ seconds: 2.5 }))
    await user.click(screen.getByLabelText('Must be used in the film')); await waitFor(() => expect(st.at(-1)?.body).toMatchObject({ id: 'p1', must: true }))
  })
})
