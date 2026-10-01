import { describe, expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import Health from '../../src/components/Health'
import { screen, setup } from '../utils/render'
import type { StageHealth } from '../../src/api'

describe('Health', () => {
  it('renders nothing when health is null or empty', () => {
    const { container, rerender } = setup(<Health />)
    expect(container).toBeEmptyDOMElement()
    rerender(<Health h={null} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<Health h={{ retrying: 0, failed: 0, attempts: 0, retries: 0, last_error: null, next_try_in_s: null, last_success_ago_s: null }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders correctly when items are retrying', () => {
    const h: StageHealth = { retrying: 2, failed: 0, attempts: 1, retries: 3, next_try_in_s: 10, sleep_s: 30, last_success_ago_s: 45, last_error: 'HTTP 500 Server Error' }
    setup(<Health h={h} />)
    expect(screen.getByText(/2 failing now/)).toBeInTheDocument()
    expect(screen.getByText(/try 1 of 3/)).toBeInTheDocument()
    expect(screen.getByText(/sleeping 10 s left of a 30 s backoff/)).toBeInTheDocument()
    expect(screen.getByText(/last success 45 s ago/)).toBeInTheDocument()
    expect(screen.getByText(/HTTP 500 Server Error/)).toBeInTheDocument()
  })

  it('renders correctly when retry sleep is 0', () => {
    const h: StageHealth = { retrying: 1, failed: 0, attempts: 2, retries: 3, next_try_in_s: 0, sleep_s: null, last_success_ago_s: 150, last_error: null }
    setup(<Health h={h} />)
    expect(screen.getByText(/done: trying now/)).toBeInTheDocument()
    expect(screen.getByText(/last success 3 min ago/)).toBeInTheDocument()
  })

  it('renders correctly when items failed and gave up', () => {
    const h: StageHealth = { retrying: 0, failed: 5, attempts: 3, retries: 3, next_try_in_s: null, sleep_s: null, last_success_ago_s: 7200, last_error: 'Traceback before\nHTTP 403 Forbidden. Other stuff after' }
    setup(<Health h={h} />)
    expect(screen.getByText(/5 gave up/)).toBeInTheDocument()
    expect(screen.getByText(/last success 2.0 h ago/)).toBeInTheDocument()
    expect(screen.getByText(/HTTP 403 Forbidden/)).toBeInTheDocument()
    expect(screen.queryByText(/Other stuff after/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Traceback before/)).not.toBeInTheDocument()
  })

  it('renders both retrying and gave up', () => {
    const h: StageHealth = { retrying: 1, failed: 2, attempts: 2, retries: 3, next_try_in_s: 5, sleep_s: 10, last_success_ago_s: null, last_error: 'Error' }
    setup(<Health h={h} />)
    expect(screen.getByText(/1 failing now/)).toBeInTheDocument()
    expect(screen.getByText(/2 gave up/)).toBeInTheDocument()
    expect(screen.getByText(/none yet/)).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    const h: StageHealth = { retrying: 2, failed: 1, attempts: 1, retries: 3, next_try_in_s: 10, sleep_s: 30, last_success_ago_s: 45, last_error: 'HTTP 500' }
    const { container } = setup(<Health h={h} />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
