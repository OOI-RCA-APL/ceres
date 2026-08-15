import { describe, expect, it } from 'vitest'

import {
  convertedPagesWidget,
  createWidget,
  defaultWidgetName,
  pagesOf,
  type Widget,
  widgetInfos,
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
  })

  it('opens every other kind with no pages at all', () => {
    expect(pagesOf(createWidget('meter'))).toHaveLength(0)
  })
})

describe('converting between the pages widget kinds', () => {
  it('carries the pages across untouched, in both directions', () => {
    for (const type of ['tabs', 'carousel'] as const) {
      const original = pagesWidget(type)
      const converted = convertedPagesWidget(original)
      expect(converted?.type).toBe(type === 'tabs' ? 'carousel' : 'tabs')
      expect(pagesOf(converted as Widget)).toStrictEqual(pagesOf(original))
    }
  })

  it('replaces a name that was only ever the old kind default', () => {
    const converted = convertedPagesWidget(pagesWidget('tabs'))
    expect(converted?.name).toBe(defaultWidgetName('carousel'))
  })

  it('keeps a name that was chosen', () => {
    const named = { ...pagesWidget('carousel'), name: 'Instrument Views' }
    expect(convertedPagesWidget(named)?.name).toBe('Instrument Views')
  })

  it('declines a widget that holds no pages', () => {
    expect(convertedPagesWidget(createWidget('meter'))).toBeNull()
  })
})
