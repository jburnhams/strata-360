import { expect, it, describe } from 'vitest'
import { Skeleton, PanelSkeleton } from '../../src/components/Skeleton'
import { setup } from '../utils/render'

describe('Skeleton', () => {
  it('renders a simple skeleton div', () => {
    const { container } = setup(<Skeleton className="custom-class" />)
    const div = container.querySelector('div')
    expect(div).toBeInTheDocument()
    expect(div).toHaveClass('animate-pulse', 'custom-class')
  })

  it('renders a PanelSkeleton with a title and default rows', () => {
    const { getByRole, getByText, container } = setup(<PanelSkeleton title="My Panel" />)
    const section = getByRole('region', { name: 'Loading My Panel' })
    expect(section).toBeInTheDocument()
    expect(getByText('My Panel')).toBeInTheDocument()
    expect(getByText('loading…')).toBeInTheDocument()

    // Default is 3 rows
    const divs = container.querySelectorAll('.animate-pulse')
    expect(divs).toHaveLength(3)
  })

  it('renders a PanelSkeleton without a title and custom rows', () => {
    const { getByRole, container } = setup(<PanelSkeleton rows={5} />)
    const section = getByRole('region', { name: 'Loading' })
    expect(section).toBeInTheDocument()

    // One for the title placeholder, plus 5 rows
    const divs = container.querySelectorAll('.animate-pulse')
    expect(divs).toHaveLength(6)
  })
})
