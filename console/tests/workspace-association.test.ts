import { describe, expect, it } from 'vitest'

import { Address } from '@/api/address'
import { type WorkspaceData, WorkspaceDataModel } from '@/workspace'
import { pinWidgetAddresses, widgetsOutside } from '@/workspace/association'

function dataOf(...widgets: Record<string, unknown>[]): WorkspaceData {
  return { layout: [{ id: 'row', widgets }] } as unknown as WorkspaceData
}

function widgetsOf(raw: Record<string, unknown>) {
  return (raw.layout as { widgets: Record<string, unknown>[] }[])[0]!.widgets
}

describe('pinWidgetAddresses', () => {
  it('resolves every relative address against the old placement, leaving defaults to follow', () => {
    const data = dataOf(
      { id: 'a', type: 'controls', buttons: [{ address: '' }, { address: '@other' }] },
      { id: 'b', type: 'procedures', procedureAddress: 'arm' },
      { id: 'c', type: 'video', query: '::queries::video' },
      { id: 'd', type: 'records', filter: { address: 'all' } },
      { id: 'e', type: 'meter', particleAddress: null },
    )

    const [a, b, c, d, e] = widgetsOf(pinWidgetAddresses(data, Address.parse('@rig')))

    expect((a!.buttons as { address: string }[]).map((button) => button.address)).toEqual([
      '',
      '@other',
    ])
    expect(b!.procedureAddress).toBe('@rig.arm')
    expect(c!.query).toBe('::queries::video')
    expect((d!.filter as { address: string }).address).toBe('@rig:all')
    expect(e!.particleAddress).toBeNull()
  })

  it('reaches a widget on a tab page and leaves the original alone', () => {
    const inner = { id: 'inner', type: 'controls', address: 'arm' }
    const data = dataOf({
      id: 'tabs',
      type: 'tabs',
      tabs: [{ id: 'page', layout: [{ id: 'row', widgets: [inner] }] }],
    })

    const pinned = pinWidgetAddresses(data, Address.parse('@rig'))

    const page = (widgetsOf(pinned)[0]!.tabs as { layout: unknown }[])[0]!
    expect(widgetsOf(page as Record<string, unknown>)[0]!.address).toBe('@rig.arm')
    expect(inner.address).toBe('arm')
  })

  it('pins parsed data into data that parses again', () => {
    const data = WorkspaceDataModel.parse({
      layout: [
        {
          widgets: [
            { type: 'controls', buttons: [{ label: 'Go', address: '@rig', action: 'go' }] },
            { type: 'procedures', procedureAddress: '@rig.arm' },
            { type: 'meter', particleAddress: '@rig.arm', particleKey: 'speed' },
            { type: 'records', filter: { address: '@rig:all' } },
            { type: 'chart', particles: [{ address: '@rig', key: 'speed' }] },
            { type: 'video', query: '::queries::video' },
            { type: 'markdown', text: 'Notes' },
          ],
        },
      ],
    })

    const result = WorkspaceDataModel.safeParse(pinWidgetAddresses(data, Address.parse('@rig')))

    expect(result.error).toBeUndefined()
    expect(result.data?.layout[0]?.widgets.map((widget) => widget.type)).toEqual(
      data.layout[0]?.widgets.map((widget) => widget.type),
    )
  })

  it('resolves against every component at the engine root', () => {
    const data = dataOf({ id: 'a', type: 'procedures', procedureAddress: 'rig', address: '' })

    const [a] = widgetsOf(pinWidgetAddresses(data, Address.parse('~')))

    expect(a!.procedureAddress).toBe('@rig')
    expect(a!.address).toBe('')
  })
})

describe('widgetsOutside', () => {
  const pinned = pinWidgetAddresses(
    dataOf(
      { id: 'a', type: 'procedures', procedureAddress: '@rig.arm' },
      { id: 'b', type: 'controls', buttons: [{ address: '@rig' }, { address: '@lens' }] },
      { id: 'c', type: 'records', filter: { address: '@:all' } },
    ),
    Address.parse('~'),
  )

  it('counts widgets naming a component the placement does not reach', () => {
    expect(widgetsOutside(pinned, '@rig')).toBe(1)
    expect(widgetsOutside(pinned, '@rig.arm')).toBe(1)
    expect(widgetsOutside(pinned, '@lens')).toBe(2)
  })

  it('finds nothing outside the engine root', () => {
    expect(widgetsOutside(pinned, '~')).toBe(0)
  })
})
