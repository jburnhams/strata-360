import { describe, expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import StylePanel from '../../src/components/StylePanel'
import type { ColourScheme } from '../../src/api'
import { mockError, mockGet, mockNetworkError, mockPending, mockPost, recordRequests } from '../utils/api'
import { makePaletteSchemes, makeTypography } from '../utils/factories'
import { screen, setup, within } from '../utils/render'

const cs = (o: Partial<ColourScheme> = {}): ColourScheme => ({ label: 'green', clips: 38, mean_loss: 0.18, tone: 'dark', base: '#f9ffb7', accent: '#fbf8ff', support: '#fff0db', light: '#eaf5fe', dark: '#111d26', outline: '#111d26', ...o })
const role = (name: string) => screen.getByRole('heading', { name }).closest('li')!

describe('StylePanel', () => {
  it('shows a skeleton while it loads and says so when it cannot', async () => {
    mockPending('/api/typography'); const { unmount } = setup(<StylePanel folder="/f" />); expect(screen.queryByRole('heading', { name: 'Look and feel' })).not.toBeInTheDocument(); unmount()
    mockNetworkError('/api/typography'); setup(<StylePanel folder="/f" />); expect(await screen.findByText('The typography could not be loaded.')).toBeInTheDocument()
  })

  it('shows the fonts of the scheme by role with a picture of each and why it was chosen', async () => {
    setup(<StylePanel folder="/f" />)
    expect(await screen.findByRole('heading', { name: 'Look and feel' })).toBeInTheDocument(); expect(screen.getByText('Barlow Condensed · Oswald · Playfair Display')).toBeInTheDocument()
    const display = within(role('Display')); expect(display.getByText('Oswald')).toBeInTheDocument(); expect(display.getByText('Oswald: matches outdoors, rugged')).toBeInTheDocument()
    const img = display.getByRole('img', { name: 'DAY 2 in Oswald' }); expect(img.getAttribute('src')).toContain('/api/typography/sample?'); expect(img.getAttribute('src')).toContain('font=oswald'); expect(img.getAttribute('src')).toContain('text=DAY+2')
    expect(within(role('Quote')).getByText('Playfair Display')).toBeInTheDocument(); expect(within(role('Numerals')).getByRole('img', { name: '3:45:12 in Barlow Condensed' })).toBeInTheDocument()
  })

  it.each([
    ['project', [], /worked out from the project/],
    ['script', ['elegant', 'refined'], /chosen by the script writer/],
    ['user', [], /your choice/],
  ] as const)('says where the vibes come from: %s', async (basis, script, text) => {
    mockGet('/api/typography', makeTypography({ scheme: { basis, style: basis === 'user' ? ['rugged'] : [], sources: { user: basis === 'user' ? ['rugged'] : [], script: basis === 'script' ? [...script] : [], inferred: [] } }, script_vibes: [...script] }))
    setup(<StylePanel folder="/f" />); expect(await screen.findByRole('heading', { name: /Vibes/ })).toHaveTextContent(text)
  })

  it('mentions the script writers proposal, and when there is none says it comes with the draft', async () => {
    mockGet('/api/typography', makeTypography({ script_vibes: ['rugged', 'quiet'] })); const { unmount } = setup(<StylePanel folder="/f" />); expect(await screen.findByText(/the script writer proposed rugged, quiet/)).toBeInTheDocument(); unmount()
    mockGet('/api/typography', makeTypography()); setup(<StylePanel folder="/f" />); expect(await screen.findByText(/the script writer proposes some with its draft/)).toBeInTheDocument()
  })

  it('marks the vibes in use and picking one sends the whole list as your choice', async () => {
    const seen = recordRequests('/api/typography'); mockPost('/api/typography', { scheme: makeTypography({ scheme: { basis: 'user', style: ['athletic', 'outdoors', 'rugged', 'cinematic', 'clean', 'elegant'] } }).scheme })
    const { user } = setup(<StylePanel folder="/f" />); const chips = within(await screen.findByRole('list', { name: 'Vibes' }))
    expect(chips.getByRole('button', { name: 'athletic' })).toHaveAttribute('aria-pressed', 'true'); expect(chips.getByRole('button', { name: 'elegant' })).toHaveAttribute('aria-pressed', 'false')
    await user.click(chips.getByRole('button', { name: 'elegant' }))
    await screen.findByRole('button', { name: 'elegant', pressed: true }); expect(seen.filter(r => r.method === 'POST')[0].body).toEqual({ folder: '/f', style: ['athletic', 'outdoors', 'rugged', 'cinematic', 'clean', 'elegant'] })
  })

  it('switching a vibe off removes it from your choice', async () => {
    mockGet('/api/typography', makeTypography({ scheme: { basis: 'user', style: ['rugged', 'quiet'], sources: { user: ['rugged', 'quiet'], script: [], inferred: [] } } })); const seen = recordRequests('/api/typography'); mockPost('/api/typography', { scheme: makeTypography().scheme })
    const { user } = setup(<StylePanel folder="/f" />); await user.click(await screen.findByRole('button', { name: 'rugged', pressed: true })); await screen.findByRole('list', { name: 'Vibes' })
    expect(seen.filter(r => r.method === 'POST')[0].body).toEqual({ folder: '/f', style: ['quiet'] })
  })

  it('offers to give the choice back to the script writer, naming its vibes', async () => {
    mockGet('/api/typography', makeTypography({ scheme: { basis: 'user', style: ['rugged'] }, script_vibes: ['elegant', 'refined'] })); const seen = recordRequests('/api/typography'); mockPost('/api/typography', { scheme: makeTypography().scheme })
    const { user } = setup(<StylePanel folder="/f" />); await user.click(await screen.findByRole('button', { name: "Use the script writer's choice again (elegant, refined)" })); await screen.findByRole('list', { name: 'Vibes' })
    expect(seen.filter(r => r.method === 'POST')[0].body).toEqual({ folder: '/f', style: [] })
  })

  it('without a script draft the button just clears your choice, and there is none when the choice is not yours', async () => {
    mockGet('/api/typography', makeTypography({ scheme: { basis: 'user', style: ['rugged'] } })); const { unmount } = setup(<StylePanel folder="/f" />); expect(await screen.findByRole('button', { name: 'Clear my choice' })).toBeInTheDocument(); unmount()
    mockGet('/api/typography', makeTypography()); setup(<StylePanel folder="/f" />); await screen.findByRole('list', { name: 'Vibes' }); expect(screen.queryByRole('button', { name: /Clear my choice|script writer's choice/ })).not.toBeInTheDocument()
  })

  it('lets you change the font of a role: the ones made for it first, then the others', async () => {
    const seen = recordRequests('/api/typography'); mockPost('/api/typography', { scheme: makeTypography({ scheme: { fonts: { display: 'playfair', subtitle: 'barlow_cond_bold', meta: 'barlow_cond_bold', numerals: 'barlow_cond_bold', quote: 'playfair' }, overrides: { display: 'playfair' } } }).scheme })
    const { user } = setup(<StylePanel folder="/f" />); await user.click(within(await screen.findByRole('heading', { name: 'Display' }).then(h => h.closest('li')!)).getByRole('button', { name: 'Change font' }))
    const grid = within(screen.getByRole('group', { name: 'Fonts for Display' })); expect(grid.getByText('Designed for this role')).toBeInTheDocument(); expect(grid.getByText(/Not designed for this role/)).toBeInTheDocument()
    expect(grid.getByRole('button', { name: /Oswald/ })).toHaveAttribute('aria-pressed', 'true'); await user.click(grid.getByRole('button', { name: /Playfair Display/ }))
    expect(await within(role('Display')).findByText('chosen by you')).toBeInTheDocument(); expect(seen.filter(r => r.method === 'POST')[0].body).toEqual({ folder: '/f', fonts: { display: 'playfair' } }); expect(screen.queryByRole('group', { name: 'Fonts for Display' })).not.toBeInTheDocument()
  })

  it('a role you changed can go back to automatic', async () => {
    mockGet('/api/typography', makeTypography({ scheme: { overrides: { quote: 'playfair' } } })); const seen = recordRequests('/api/typography'); mockPost('/api/typography', { scheme: makeTypography().scheme })
    const { user } = setup(<StylePanel folder="/f" />); await screen.findByRole('heading', { name: 'Quote' }); expect(within(role('Display')).queryByRole('button', { name: 'Back to automatic' })).not.toBeInTheDocument()
    await user.click(within(role('Quote')).getByRole('button', { name: 'Back to automatic' })); await within(role('Quote')).findByText('chosen for the vibes')
    expect(seen.filter(r => r.method === 'POST')[0].body).toEqual({ folder: '/f', fonts: { quote: null } })
  })

  it('opens and closes the font grid of one role at a time', async () => {
    const { user } = setup(<StylePanel folder="/f" />); await screen.findByRole('heading', { name: 'Display' })
    await user.click(within(role('Display')).getByRole('button', { name: 'Change font' })); await user.click(within(role('Quote')).getByRole('button', { name: 'Change font' }))
    expect(screen.queryByRole('group', { name: 'Fonts for Display' })).not.toBeInTheDocument(); expect(screen.getByRole('group', { name: 'Fonts for Quote' })).toBeInTheDocument()
    await user.click(within(role('Quote')).getByRole('button', { name: 'Close' })); expect(screen.queryByRole('group', { name: 'Fonts for Quote' })).not.toBeInTheDocument()
  })

  it('shows what the server refused and leaves the scheme as it was', async () => {
    mockError('/api/typography', 400, 'not vibes of the library: [x]', 'post'); const { user } = setup(<StylePanel folder="/f" />); await user.click(await screen.findByRole('button', { name: 'warm' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not vibes of the library'); expect(within(role('Display')).getByText('Oswald')).toBeInTheDocument()
  })

  it('disables the choices while one is being saved', async () => {
    mockPending('/api/typography', 'post'); const { user } = setup(<StylePanel folder="/f" />); await user.click(await screen.findByRole('button', { name: 'warm' }))
    expect(screen.getByRole('button', { name: 'elegant' })).toBeDisabled()
  })

  it('shows the colour schemes with their swatches and how many clips use each', async () => {
    mockGet('/api/palette-schemes', makePaletteSchemes({ present: true, clips: 61, schemes: [cs(), cs({ label: 'indigo', clips: 15, base: '#6bb0f3' }), cs({ label: 'violet', clips: 1 })] })); setup(<StylePanel folder="/f" />)
    const list = within(await screen.findByRole('list', { name: 'Colour schemes' })); expect(list.getAllByRole('listitem')).toHaveLength(3); expect(list.getByText('green')).toBeInTheDocument(); expect(list.getByText(/38 clips/)).toBeInTheDocument(); expect(list.getByText(/1 clip$/)).toBeInTheDocument()
    expect(list.getAllByTitle('#6bb0f3')).toHaveLength(1)
  })

  it('without colour schemes it says how to make them, and uses the first schemes colour for the font pictures', async () => {
    const { unmount } = setup(<StylePanel folder="/f" />); expect(await screen.findByText(/No colour schemes yet/)).toBeInTheDocument(); expect(screen.getByRole('img', { name: 'DAY 2 in Oswald' }).getAttribute('src')).toContain('color=%23e7e5e4'); unmount()
    mockGet('/api/palette-schemes', makePaletteSchemes({ present: true, schemes: [cs({ base: '#6bb0f3' })] })); setup(<StylePanel folder="/f" />)
    await screen.findByRole('list', { name: 'Colour schemes' }); await screen.findByRole('img', { name: 'DAY 2 in Oswald' }); await new Promise(r => setTimeout(r, 50)); expect(screen.getByRole('img', { name: 'DAY 2 in Oswald' }).getAttribute('src')).toContain('color=%236bb0f3')
  })

  it('still shows a scheme that lacks the newer fields (a file of an earlier version)', async () => {
    const t = makeTypography(); const old = { ...t, scheme: { fonts: t.scheme.fonts, vibes: t.scheme.vibes } } as unknown as typeof t; mockGet('/api/typography', old)
    setup(<StylePanel folder="/f" />); expect(await screen.findByRole('heading', { name: 'Display' })).toBeInTheDocument(); expect(screen.getByRole('heading', { name: /Vibes/ })).toHaveTextContent(/worked out from the project/)
  })

  it('has no accessibility violations, with a font grid open too', async () => {
    mockGet('/api/palette-schemes', makePaletteSchemes({ present: true, schemes: [cs()] })); const { user, container } = setup(<StylePanel folder="/f" />)
    await user.click(within(await screen.findByRole('heading', { name: 'Display' }).then(h => h.closest('li')!)).getByRole('button', { name: 'Change font' })); expect(await axe(container)).toHaveNoViolations()
  })
})
