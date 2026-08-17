import { describe, expect, it } from 'vitest'

import { isStructurallyEqual } from '@/utilities'
import {
  comparableWorkspaceData,
  type ControlsWidget,
  defaultWidgetName,
  type MeterWidget,
  pagesOf,
  type Widget,
  WorkspaceDataModel,
} from '@/workspace'

describe('defaultWidgetName', () => {
  it('says what each kind is called before anything is made of it', () => {
    expect(defaultWidgetName('tabs')).toBe('Tabs')
    expect(defaultWidgetName('carousel')).toBe('Carousel')
  })

  it('tells a chosen name from an inherited one', () => {
    expect('Instrument Views').not.toBe(defaultWidgetName('tabs'))
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

describe('a stored button widget', () => {
  /** The widgets a stored workspace holds, once it has been read the way the app reads one. */
  function loaded(...widgets: unknown[]): Widget[] {
    const data = WorkspaceDataModel.parse({
      layout: [{ id: 'r1', height: 250, collapsed: false, widgets }],
    })

    return data.layout[0]?.widgets ?? []
  }

  function buttonsOf(widget: Widget): ControlsWidget['buttons'] {
    return (widget as ControlsWidget).buttons
  }

  it('comes back as a controls widget, the kind it is stored under now', () => {
    const [upgraded] = loaded({ id: 'w1', type: 'button', name: '' })

    expect(upgraded?.type).toBe('controls')
  })

  it('becomes a widget holding the single button it always was', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'button',
      name: '',
      address: '@engine.thing',
      action: 'restart',
      label: 'Restart',
      arguments: { force: true },
    })

    expect(buttonsOf(upgraded as Widget)).toHaveLength(1)
    expect(buttonsOf(upgraded as Widget)[0]?.action).toBe('restart')
    expect(buttonsOf(upgraded as Widget)[0]?.label).toBe('Restart')
    expect(buttonsOf(upgraded as Widget)[0]?.arguments).toEqual({ force: true })
  })

  it('holds no buttons when nothing was ever made of it', () => {
    const [upgraded] = loaded({ id: 'w1', type: 'button', name: '', arguments: {} })

    expect(buttonsOf(upgraded as Widget)).toEqual([])
  })

  it('leaves the fields it was stored with behind', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'button',
      name: '',
      action: 'restart',
      arguments: { force: true },
    })

    expect(upgraded).not.toHaveProperty('action')
    expect(upgraded).not.toHaveProperty('arguments')
  })

  it('comes back with a confirm up and its arguments unlocked', () => {
    const [upgraded] = loaded({ id: 'w1', type: 'button', name: '', action: 'restart' })

    expect(buttonsOf(upgraded as Widget)[0]?.locked).toBe(false)
    expect(buttonsOf(upgraded as Widget)[0]?.confirm).toBe(true)
  })

  it('is written back and read again as exactly what it was', () => {
    const [first] = loaded({
      id: 'w1',
      type: 'button',
      name: '',
      address: '@engine.thing',
      action: 'restart',
      arguments: { force: true },
    })
    // Both safeguards are on by default so turning them off is what has to survive the trip.
    const firstButton = buttonsOf(first as Widget)[0]
    if (firstButton != null) {
      firstButton.confirm = false
      firstButton.locked = false
    }

    // The trip a workspace makes every time it is saved and opened again.
    const [second] = loaded(JSON.parse(JSON.stringify(first)))
    const button = buttonsOf(second as Widget)[0]

    expect(buttonsOf(second as Widget)).toHaveLength(1)
    expect(button?.id).toBe(firstButton?.id)
    expect(button?.address?.toString()).toBe('@engine.thing')
    expect(button?.action).toBe('restart')
    expect(button?.arguments).toEqual({ force: true })
    expect(button?.confirm).toBe(false)
    expect(button?.locked).toBe(false)
  })

  it('is left alone once it holds buttons of its own', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'button',
      name: '',
      buttons: [
        { id: 'b1', action: 'one' },
        { id: 'b2', action: 'two' },
      ],
      action: 'legacy',
    })

    expect(buttonsOf(upgraded as Widget).map((button) => button.action)).toEqual(['one', 'two'])
  })

  it('is reached inside a carousel slide', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'carousel',
      name: 'Carousel',
      slides: [
        {
          id: 's1',
          name: '',
          layout: [
            {
              id: 'r2',
              height: 250,
              collapsed: false,
              widgets: [{ id: 'w2', type: 'button', name: '', action: 'restart' }],
            },
          ],
        },
      ],
    })

    const inside = pagesOf(upgraded as Widget)[0]?.layout[0]?.widgets[0]
    expect(buttonsOf(inside as Widget).map((button) => button.action)).toEqual(['restart'])
  })

  it('is reached inside a tab strip page', () => {
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
              widgets: [{ id: 'w2', type: 'button', name: '', action: 'restart' }],
            },
          ],
        },
      ],
    })

    const inside = pagesOf(upgraded as Widget)[0]?.layout[0]?.widgets[0]
    expect(buttonsOf(inside as Widget).map((button) => button.action)).toEqual(['restart'])
  })

  it('wears a frame by default, the same as every other widget', () => {
    const [button, chart] = loaded(
      { id: 'w1', type: 'button', name: '' },
      { id: 'w2', type: 'chart', name: 'Chart' },
    )

    expect(button?.frameless).toBe(false)
    expect(chart?.frameless).toBe(false)
  })
})

describe('a stored value widget', () => {
  /** The widgets a stored workspace holds, once it has been read the way the app reads one. */
  function loaded(...widgets: unknown[]): Widget[] {
    const data = WorkspaceDataModel.parse({
      layout: [{ id: 'r1', height: 250, collapsed: false, widgets }],
    })

    return data.layout[0]?.widgets ?? []
  }

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
