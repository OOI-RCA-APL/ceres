import { describe, expect, it } from 'vitest'

import { Address, engineRoot } from '@/api/address'
import {
  convertedPagesWidget,
  createWidget,
  defaultWidgetName,
  filesWidgetRoot,
  pagesOf,
  type Widget,
  widgetInfos,
  WidgetModel,
  withPages,
} from '@/workspace'

/** A pages widget of `type` carrying two named pages, one of them holding a widget. */
function pagesWidget(type: 'tabs' | 'carousel'): Widget {
  return withPages(createWidget(type), [
    { id: 'page-1', name: 'Instruments', layout: [] },
    {
      id: 'page-2',
      name: '',
      layout: [
        {
          id: 'row-1',
          height: 200,
          collapsed: false,
          widgets: [createWidget('meter')],
        },
      ],
    },
  ])
}

describe('the widget registry', () => {
  it('offers a real component for every kind it lists', () => {
    for (const info of Object.values(widgetInfos)) {
      expect(info.component, info.type).not.toBeUndefined()
    }
  })

  it('opens a pages widget on a page, since one with none has no layout to drop into', () => {
    expect(pagesOf(createWidget('tabs'))).toHaveLength(1)
    expect(pagesOf(createWidget('carousel'))).toHaveLength(1)
    expect(pagesOf(createWidget('section'))).toHaveLength(1)
  })

  it('opens every other kind with no pages at all', () => {
    expect(pagesOf(createWidget('meter'))).toHaveLength(0)
  })

  it('stores where a files widget lists and opens', () => {
    expect(createWidget('files')).toMatchObject({ type: 'files', name: 'Files', path: [] })
    const stored = WidgetModel.parse({ type: 'files', component: 'a', mount: 'abc', path: ['b'] })
    expect(stored).toMatchObject({ type: 'files', component: 'a', mount: 'abc', path: ['b'] })
  })

  it('lists a files widget under its component, or every mount from the engine root', () => {
    const scope = Address.parse('@a')
    expect(filesWidgetRoot(null, scope)).toBe('@a')
    expect(filesWidgetRoot('b', scope)).toBe('@a.b')
    expect(filesWidgetRoot(engineRoot, scope)).toBeNull()
    expect(filesWidgetRoot(null, Address.parse(engineRoot))).toBeNull()
  })
})

describe('converting between the pages widget kinds', () => {
  it('carries the pages across untouched between tabs and a carousel', () => {
    for (const [from, to] of [
      ['tabs', 'carousel'],
      ['carousel', 'tabs'],
    ] as const) {
      const original = pagesWidget(from)
      const converted = convertedPagesWidget(original, to)
      expect(converted?.type).toBe(to)
      expect(pagesOf(converted as Widget)).toStrictEqual(pagesOf(original))
    }
  })

  it('folds every page into the one a section holds, keeping the first page ID', () => {
    const original = pagesWidget('tabs')
    const section = convertedPagesWidget(original, 'section') as Widget
    expect(pagesOf(section)).toStrictEqual([
      { id: 'page-1', name: '', layout: pagesOf(original).flatMap((page) => page.layout) },
    ])
  })

  it('turns a section into a single unnamed page of the other kinds', () => {
    const section = convertedPagesWidget(pagesWidget('tabs'), 'section') as Widget
    const tabs = convertedPagesWidget(section, 'tabs') as Widget
    expect(pagesOf(tabs)).toStrictEqual(pagesOf(section))
  })

  it('carries over how the leftover height is spread', () => {
    const original = { ...pagesWidget('tabs'), expand: 'even', shrink: true } as Widget
    expect(convertedPagesWidget(original, 'section')).toMatchObject({
      expand: 'even',
      shrink: true,
    })
  })

  it('replaces a name that was only ever the old kind default', () => {
    const converted = convertedPagesWidget(pagesWidget('tabs'), 'carousel')
    expect(converted?.name).toBe(defaultWidgetName('carousel'))
  })

  it('keeps a name that was chosen', () => {
    const named = { ...pagesWidget('carousel'), name: 'Instrument Views' }
    expect(convertedPagesWidget(named, 'section')?.name).toBe('Instrument Views')
  })

  it('declines a widget that holds no pages, or is already of that kind', () => {
    expect(convertedPagesWidget(createWidget('meter'), 'tabs')).toBeNull()
    expect(convertedPagesWidget(pagesWidget('tabs'), 'tabs')).toBeNull()
  })
})
