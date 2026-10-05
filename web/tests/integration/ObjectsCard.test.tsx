import { describe, expect, it, vi } from 'vitest'
import { screen, setup, within } from '../utils/render'
import ObjectsCard, { framing, framingArea, where } from '../../src/components/ObjectsCard'
import { makeObject, makeObjects, makeRegion } from '../utils/factories'

const render = (info: Parameters<typeof ObjectsCard>[0]['info'], o: { marked?: boolean; onMarked?: (b: boolean) => void; onLook?: (l: never) => void; onHide?: (...a: never[]) => void } = {}) =>
  setup(<ObjectsCard folder="/data" clip="CAM_1" info={info} marked={o.marked ?? true} onMarked={o.onMarked ?? (() => {})} onLook={(o.onLook ?? (() => {})) as never} onHide={o.onHide as never} />)

describe('ObjectsCard: the things passed in a clip', () => {
  it('says so when the stage has not run, or why the clip was not looked at', () => {
    const { unmount } = render(null); expect(screen.getByText(/objects stage has not run/)).toBeInTheDocument(); unmount()
    render(makeObjects({ skipped: 'night: the sun is -36 degrees and the exposure is dim' })); expect(screen.getByText(/Not looked at: night/)).toBeInTheDocument()
  })

  it('lists each thing with its picture, name, direction, size and when it was in view, earliest first', () => {
    render(makeObjects({ objects: [makeObject({ id: 1, label: 'church steeple', yoloe: 'house', lon: -115, lat: 16, deg: 3.5, seen: [8.5], best_t: 8.5 }), makeObject({ id: 0, label: 'goat', yoloe: 'cow', lon: -90, lat: -5, deg: 4, seen: [1, 8.5, 20] })] }))
    const rows = screen.getAllByRole('listitem'); expect(rows).toHaveLength(2); expect(within(rows[0]).getByText('goat')).toBeInTheDocument(); expect(within(rows[0]).getByText(/270°.*4\.0° wide.*in view 0:01 and 2 more times.*detector said “cow”/)).toBeInTheDocument()
    expect(within(rows[1]).getByText(/245°, 16° up.*3\.5° wide.*in view 0:08/)).toBeInTheDocument(); expect(rows[0].querySelector('img')).toHaveAttribute('src', '/api/clip/object?folder=%2Fdata&clip=CAM_1&id=0')
  })

  it('has a grey box for a thing with no picture, and does not repeat the detector\'s word when the name already says it', () => {
    render(makeObjects({ objects: [makeObject({ crop: false, label: 'brown cow', yoloe: 'cow' }), makeObject({ id: 2, source: 'detector', label: 'sign', yoloe: 'sign' })] }))
    const rows = screen.getAllByRole('listitem'); expect(rows[0].querySelector('img')).toBeNull(); expect(within(rows[0]).queryByText(/detector said/)).toBeNull(); expect(within(rows[1]).getByText(/trusted detector word/)).toBeInTheDocument()
  })

  it('turns the player to a thing when asked, framed to its size', async () => {
    const onLook = vi.fn(); const { user } = render(makeObjects({ objects: [makeObject({ lon: -90, lat: -5, deg: 4, best_t: 2.5 })] }), { onLook })
    await user.click(screen.getByRole('button', { name: 'Look at goat' })); expect(onLook).toHaveBeenCalledWith({ lon: -90, lat: -5, fov: 40, t: 2.5 })
  })

  it('shows the first twelve and the rest on request', async () => {
    const many = Array.from({ length: 15 }, (_, i) => makeObject({ id: i, label: `thing ${i}`, seen: [i], best_t: i })); const { user } = render(makeObjects({ objects: many }))
    expect(screen.getAllByRole('listitem')).toHaveLength(12); await user.click(screen.getByRole('button', { name: 'show all 15' })); expect(screen.getAllByRole('listitem')).toHaveLength(15)
    await user.click(screen.getByRole('button', { name: 'show fewer' })); expect(screen.getAllByRole('listitem')).toHaveLength(12)
  })

  it('lists the areas of snow and water, biggest first within each, with a button to look at each', async () => {
    const onLook = vi.fn(); const { user } = render(makeObjects({ objects: [], regions: [makeRegion({ kind: 'water', lon: 80, lat: -25, w_deg: 40, h_deg: 12, seen: [11.5] }), makeRegion({ kind: 'snow', w_deg: 10, h_deg: 5 }), makeRegion({ kind: 'snow', lon: 100, lat: -10, w_deg: 60, h_deg: 20, seen: [3, 23] })] }), { onLook })
    expect(screen.getByText(/0 things, 3 areas of snow or water/)).toBeInTheDocument(); const rows = screen.getAllByRole('listitem'); expect(rows.map(r => r.textContent?.slice(0, 5))).toEqual(['Snow ', 'Snow ', 'Water'])
    expect(within(rows[0]).getByText(/100°, 10° down · 60° × 20° · in view 0:03 and 1 more/)).toBeInTheDocument()
    await user.click(within(rows[2]).getByRole('button')); expect(onLook).toHaveBeenCalledWith({ lon: 80, lat: -25, fov: 60, t: 11.5 })
  })

  it('switches the marks on the video, and mentions scenery it left out', async () => {
    const onMarked = vi.fn(); const { user } = render(makeObjects({ scenery_labels: { 'tree trunk': 14, 'tree branch': 3 } }), { marked: true, onMarked })
    await user.click(screen.getByRole('checkbox', { name: 'Show on the video' })); expect(onMarked).toHaveBeenCalledWith(false); expect(screen.getByText(/Scenery not listed: tree trunk \(14\), tree branch \(3\)/)).toBeInTheDocument()
  })

  it('says when nothing was found', () => { render(makeObjects({ objects: [], regions: [] })); expect(screen.getByText('Nothing found.')).toBeInTheDocument() })
})

describe('ObjectsCard: hiding things', () => {
  const info = () => makeObjects({ objects: [makeObject({ id: 0, label: 'goat', seen: [1] }), makeObject({ id: 1, label: 'sunlight', yoloe: 'sun', hidden: 'stop', seen: [2] }), makeObject({ id: 2, label: 'tall trees', hidden: 'scenery', seen: [3] }),
    makeObject({ id: 3, label: 'sign', hidden: 'object', seen: [4] }), makeObject({ id: 4, label: 'log', hidden: 'label', seen: [5] })] })

  it('leaves out what is hidden and says how many are, with a switch to list them all', async () => {
    const { user } = render(info(), { onHide: vi.fn() }); expect(screen.getAllByRole('listitem')).toHaveLength(1); expect(screen.getByText(/1 thing, from/)).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Show 4 hidden' })); expect(screen.getAllByRole('listitem')).toHaveLength(5); expect(screen.getByText(/1 thing, from/)).toBeInTheDocument()                  // (the count of things stays the visible ones)
    await user.click(screen.getByRole('checkbox', { name: 'Show 4 hidden' })); expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })

  it('says why each hidden one is hidden, and lets you show again only what you hid yourself', async () => {
    const onHide = vi.fn(); const { user } = render(info(), { onHide }); await user.click(screen.getByRole('checkbox', { name: 'Show 4 hidden' }))
    for (const why of [/on the list of what is not a thing/, /on the list of scenery/, /hidden by you: this one/, /hidden by you: every one with this name/]) expect(screen.getByText(why)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show sunlight again' })).toBeNull(); expect(screen.queryByRole('button', { name: 'Show tall trees again' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Show sign again' })); expect(onHide).toHaveBeenLastCalledWith(expect.objectContaining({ id: 3 }), 'object', false)
    await user.click(screen.getByRole('button', { name: 'Show log again' })); expect(onHide).toHaveBeenLastCalledWith(expect.objectContaining({ id: 4 }), 'label', false)
  })

  it('hides one thing, or every thing with its name', async () => {
    const onHide = vi.fn(); const { user } = render(info(), { onHide })
    await user.click(screen.getByRole('button', { name: 'Hide goat' })); expect(onHide).toHaveBeenLastCalledWith(expect.objectContaining({ id: 0 }), 'object', true)
    await user.click(screen.getByRole('button', { name: 'Hide every goat' })); expect(onHide).toHaveBeenLastCalledWith(expect.objectContaining({ id: 0 }), 'label', true)
  })

  it('has no hide buttons when it cannot hide, and no hidden switch when nothing is hidden', () => {
    render(makeObjects()); expect(screen.queryByRole('button', { name: /^Hide/ })).toBeNull(); expect(screen.queryByRole('checkbox', { name: /hidden/ })).toBeNull()
  })
})

describe('where and framing', () => {
  it('give a bearing in 0 to 360 degrees with the height when it is more than a few degrees off the horizon, and a field of view of four times the size between 40 and 100', () => {
    expect(where(-90, 0)).toBe('270°'); expect(where(370, -12)).toBe('10°, 12° down'); expect(where(0, 4.9)).toBe('0°'); expect(framing(2)).toBe(40); expect(framing(15)).toBe(60); expect(framing(50)).toBe(100)
    expect(framingArea(10, 5)).toBe(60); expect(framingArea(40, 12)).toBe(60); expect(framingArea(60, 40)).toBe(92); expect(framingArea(200, 10)).toBe(140)
  })
})
