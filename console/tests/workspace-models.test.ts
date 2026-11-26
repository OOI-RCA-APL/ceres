import { describe, expect, it } from 'vitest'

import { Address } from '@/api/address'
import { isStructurallyEqual } from '@/utilities'
import {
  type ButtonWidget,
  ChartWidgetModel,
  comparableWorkspaceData,
  createWidget,
  defaultWidgetName,
  type MeterWidget,
  pagesOf,
  resolveWidgetAddress,
  type SectionWidget,
  type Widget,
  WorkspaceDataModel,
} from '@/workspace'

describe('resolveWidgetAddress', () => {
  const resolved = (value: string | null, scope: string) =>
    resolveWidgetAddress(value, Address.parse(scope))?.toString() ?? null

  it("defaults an unset or empty field to the workspace's component", () => {
    expect(resolved(null, '@rig')).toBe('@rig')
    expect(resolved('', '@rig')).toBe('@rig')
  })

  it('defaults to nothing at the engine root', () => {
    expect(resolved(null, '~')).toBeNull()
    expect(resolved('', '~')).toBeNull()
  })

  it('resolves a relative field under the workspace and keeps an absolute one', () => {
    expect(resolved('arm', '@rig')).toBe('@rig.arm')
    expect(resolved('@other', '@rig')).toBe('@other')
  })
})

describe('defaultWidgetName', () => {
  it('says what each kind is called before anything is made of it', () => {
    expect(defaultWidgetName('tabs')).toBe('Tabs')
    expect(defaultWidgetName('carousel')).toBe('Carousel')
  })

  it('tells a chosen name from an inherited one', () => {
    expect('Instrument Views').not.toBe(defaultWidgetName('tabs'))
  })
})

describe('a chart widget', () => {
  it('fits the series its legend leaves on, and does not reach for zero', () => {
    expect(createWidget('chart')).toMatchObject({ fit: 'shown-data', fromZero: false })
  })

  it('reads its values out to two decimal places', () => {
    expect(createWidget('chart')).toMatchObject({ decimals: 2 })
  })

  it('keeps the fit it was stored with', () => {
    expect(ChartWidgetModel.parse({ type: 'chart', fit: 'all-data' }).fit).toBe('all-data')
  })

  it('draws each series in the shape it chose, falling back to a line', () => {
    const widget = ChartWidgetModel.parse({
      type: 'chart',
      particles: [{ series: [{ field: 'pressure' }, { field: 'temperature', type: 'scatter' }] }],
    })

    expect(widget.particles[0]?.series.map((series) => series.type)).toEqual(['line', 'scatter'])
  })
})

describe('a stored widget of an unknown kind', () => {
  it('is kept exactly as it came rather than dropped', () => {
    const data = WorkspaceDataModel.parse({
      layout: [
        {
          id: 'r1',
          height: 250,
          collapsed: false,
          widgets: [
            { id: 'w1', name: 'UI', width: 120, type: 'ui', interfaceAddress: '@driver' },
            { id: 'w2', name: 'w2', width: 120, type: 'logs', filter: {} },
          ],
        },
      ],
    })
    const held = data.layout[0]?.widgets[0] as unknown as { type: string; interfaceAddress: string }

    expect(held?.type).toBe('ui')
    expect(held?.interfaceAddress).toBe('@driver')
    expect(data.layout[0]?.widgets[1]?.type).toBe('logs')
  })
})

/** The widgets a stored workspace holds, once it has been read the way the app reads one. */
function loaded(...widgets: unknown[]): Widget[] {
  const data = WorkspaceDataModel.parse({
    layout: [{ id: 'r1', height: 250, collapsed: false, widgets }],
  })

  return data.layout[0]?.widgets ?? []
}

describe('a stored button widget', () => {
  const stored = {
    id: 'w1',
    type: 'button',
    name: 'Card',
    label: 'Restart',
    address: '@rig',
    action: 'restart',
    arguments: { force: true },
  }

  it('is a button widget named by its label', () => {
    const [button] = loaded(stored) as ButtonWidget[]

    expect(button).toMatchObject({
      id: 'w1',
      type: 'button',
      name: 'Restart',
      action: 'restart',
      arguments: { force: true },
      locked: false,
      confirm: true,
    })
    expect(button).not.toHaveProperty('label')
  })

  it('is written back and read again as exactly what it was', () => {
    const [first] = loaded(stored) as ButtonWidget[]
    Object.assign(first as ButtonWidget, { confirm: false, locked: true })

    const [second] = loaded(JSON.parse(JSON.stringify(first)))

    expect(second).toEqual(first)
  })

  it.each([
    ['carousel', 'slides'],
    ['tabs', 'tabs'],
  ])('is reached inside a %s page', (type, key) => {
    const [holder] = loaded({
      id: 'w0',
      type,
      [key]: [{ id: 'p1', layout: [{ id: 'r2', widgets: [stored] }] }],
    })

    const inside = pagesOf(holder as Widget)[0]?.layout[0]?.widgets[0]
    expect(inside).toMatchObject({ type: 'button', name: 'Restart' })
  })
})

describe('a stored controls widget', () => {
  const stored = {
    id: 'c1',
    type: 'controls',
    name: 'Rig',
    width: 60,
    frameless: true,
    buttons: [
      { id: 'b1', label: 'Go', action: 'go' },
      { id: 'b2', action: 'stop' },
    ],
  }

  it('becomes a section laying its buttons out side by side', () => {
    const [section] = loaded(stored) as SectionWidget[]
    const page = section?.pages[0]

    expect(section).toMatchObject({ id: 'c1', type: 'section', name: 'Rig', width: 60 })
    expect(section?.frameless).toBe(true)
    expect(page?.arrange).toBe('flex')
    expect(page?.layout).toHaveLength(1)
    expect(page?.layout[0]?.height).toBe('auto')
    expect(page?.layout[0]?.widgets).toMatchObject([
      { id: 'b1', type: 'button', name: 'Go', action: 'go' },
      { id: 'b2', type: 'button', name: '', action: 'stop' },
    ])
  })

  it('reads the same on every parse, so it never shows as edited', () => {
    const parse = () => WorkspaceDataModel.parse({ layout: [{ id: 'r1', widgets: [stored] }] })

    expect(
      isStructurallyEqual(comparableWorkspaceData(parse()), comparableWorkspaceData(parse())),
    ).toBe(true)
  })

  it('is what a stored button holding buttons of its own becomes too', () => {
    const [section] = loaded({ ...stored, type: 'button', action: 'legacy' }) as SectionWidget[]

    expect(section?.type).toBe('section')
    expect(section?.pages[0]?.layout[0]?.widgets.map((widget) => widget.id)).toEqual(['b1', 'b2'])
  })
})

describe('a stored page', () => {
  it('lays its widgets out as rows unless it says otherwise', () => {
    const [section] = loaded({ id: 's1', type: 'section', pages: [{ id: 'p1' }] })

    expect(pagesOf(section as Widget)[0]?.arrange).toBe('rows')
  })
})

describe('a stored value widget', () => {
  it('comes back as a meter widget, the kind it is stored under now', () => {
    const [upgraded] = loaded({ id: 'w1', type: 'value', name: 'Depth' })

    expect(upgraded?.type).toBe('meter')
    expect(upgraded?.name).toBe('Depth')
  })

  it('keeps the fields it was stored with', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'value',
      name: 'Pressure',
      particleAddress: '@scpr',
      particleType: 'science',
      particleField: 'pressure',
      fontSize: 24,
      prefix: '~',
      suffix: ' kPa',
    })
    const meter = upgraded as MeterWidget

    expect(meter.particleAddress?.toString()).toBe('@scpr')
    expect(meter.particleType).toBe('science')
    expect(meter.particleField).toBe('pressure')
    expect(meter.fontSize).toBe(24)
    expect(meter.prefix).toBe('~')
    expect(meter.suffix).toBe(' kPa')
  })

  it('is renamed inside a tab strip page too', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'tabs',
      name: 'Tabs',
      tabs: [
        {
          id: 't1',
          name: '',
          layout: [
            {
              id: 'r2',
              height: 250,
              collapsed: false,
              widgets: [{ id: 'w2', type: 'value', name: 'Depth' }],
            },
          ],
        },
      ],
    })

    expect(pagesOf(upgraded as Widget)[0]?.layout[0]?.widgets[0]?.type).toBe('meter')
  })
})

describe('a stored row', () => {
  it('keeps a height sized to its contents', () => {
    const data = WorkspaceDataModel.parse({ layout: [{ id: 'r1', height: 'auto', widgets: [] }] })

    expect(data.layout[0]?.height).toBe('auto')
  })

  it('falls back to a fixed height it cannot read', () => {
    const data = WorkspaceDataModel.parse({ layout: [{ id: 'r1', height: 'tall', widgets: [] }] })

    expect(data.layout[0]?.height).toBe(250)
  })
})

describe('comparableWorkspaceData', () => {
  /** A stored chart widget with an ID-less series, the legacy shape a workspace saved before
  series carried one still holds. */
  function rawChartRow(field: string) {
    return {
      id: 'r1',
      height: 250,
      collapsed: false,
      widgets: [
        {
          id: 'w1',
          type: 'chart',
          name: 'Chart',
          particles: [{ type: 'temperature', series: [{ field }] }],
        },
      ],
    }
  }

  it('treats two parses of the same ID-less chart series as equal', () => {
    const first = WorkspaceDataModel.parse({ layout: [rawChartRow('value')] })
    const second = WorkspaceDataModel.parse({ layout: [rawChartRow('value')] })

    // Each parse mints its own series ID, so the parses themselves differ.
    expect(isStructurallyEqual(first, second)).toBe(false)

    expect(
      isStructurallyEqual(comparableWorkspaceData(first), comparableWorkspaceData(second)),
    ).toBe(true)
  })

  it('still reports a real difference in the series', () => {
    const first = WorkspaceDataModel.parse({ layout: [rawChartRow('value')] })
    const second = WorkspaceDataModel.parse({ layout: [rawChartRow('other')] })

    expect(
      isStructurallyEqual(comparableWorkspaceData(first), comparableWorkspaceData(second)),
    ).toBe(false)
  })
})
