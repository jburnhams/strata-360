import { describe, expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { setup } from '../utils/render'
import Moments from '../../src/components/Moments'
import type { Candidate, Unusable } from '../../src/api'

describe('Moments', () => {
  it('renders an empty state when usable is null', () => {
    const { getByText } = setup(<Moments duration={100} usable={null} />)
    expect(getByText('Moments are worked out once the other stages have finished.')).toBeInTheDocument()
  })

  it('renders a mix of usable candidates and unusable segments', async () => {
    const usable: Candidate[] = [
      { id: 'c1', start_s: 10, end_s: 20, start_utc: 'utc', quality: 0.8, energy: 0.5, features: { speech: 0.8 }, settings: ['auto'], people: 1, kind: 'speech', priority: 1, why: { starts_because: 'started', steadiness: 0.9, shake_dps: 5, exposure_ok: 1, scenic: 0.5, lens_blocked: 0, score: 0.8, speech: true, chatter: 0 } },
      { id: 'c2', start_s: 30, end_s: 40, start_utc: 'utc', quality: 0.6, energy: 0.5, features: { speech: 0.1 }, settings: ['auto'], people: 0, kind: 'span', priority: 2, why: { starts_because: 'started', steadiness: 0.7, shake_dps: 15, exposure_ok: 1, scenic: 0.2, lens_blocked: 0, score: 0.6, speech: false, chatter: 0 } }
    ]
    const unusable: Unusable[] = [
      { start_s: 0, end_s: 10, usable: false, reasons: ['shake'], detail: null, starts_because: 'shaky', stats: { score: 0.1, steadiness: 0.1, shake_dps: 60, exposure_ok: 1 } },
      { start_s: 20, end_s: 30, usable: false, reasons: ['exposure'], detail: 'dark', starts_because: 'dark', stats: { score: 0.2, steadiness: 0.8, shake_dps: 10, exposure_ok: 0 } }
    ]

    const { getByText, user, container } = setup(<Moments duration={100} usable={usable} unusable={unusable} />)

    // Check total usable summary
    expect(getByText('10 s of 100 s usable.', { exact: false })).toBeInTheDocument()

    // Check candidate rendering
    expect(getByText('you talk')).toBeInTheDocument()
    expect(getByText('0:10–0:20')).toBeInTheDocument()
    expect(getByText('💬')).toBeInTheDocument()

    expect(getByText('whole')).toBeInTheDocument()
    expect(getByText('0:30–0:40')).toBeInTheDocument()

    // Check unusable rendering
    expect(getByText('not usable: shake')).toBeInTheDocument()
    expect(getByText('not usable: exposure')).toBeInTheDocument()

    // Check hover tooltip on a usable candidate
    const firstSpan = getByText('0:10–0:20').closest('div')
    if (firstSpan) {
      await user.hover(firstSpan)
      expect(getByText('0:10–0:20 (10 s) · usable')).toBeInTheDocument()
      expect(getByText('score 0.8 · steadiness 90% (shake 5°/s) · exposure 100% ok · scenic 0.5 · lens blocked 0%')).toBeInTheDocument()
      expect(getByText('starts: started', { exact: false })).toBeInTheDocument()
    }

    // Check hover tooltip on an unusable segment
    const darkSpan = getByText('not usable: exposure').closest('div')
    if (darkSpan) {
      await user.hover(darkSpan)
      expect(getByText('0:20–0:30 (10 s) · not usable')).toBeInTheDocument()
      expect(getByText('exposure')).toBeInTheDocument(); expect(getByText('dark')).toBeInTheDocument()
      expect(getByText('score 0.2 · steadiness 80% (shake 10°/s) · exposure 0% ok')).toBeInTheDocument()
    }

    const results = await axe(container)
    // findings: nested divs acting as tooltips lack appropriate roles/aria attributes, and color contrast on backgrounds may fail,
    // also the list isn't a sematic list
    expect(results).toHaveNoViolations()
  })
})
