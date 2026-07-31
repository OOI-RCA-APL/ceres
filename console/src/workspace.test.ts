import { describe, expect, it } from 'vitest'

import {
  collectLayouts,
  layoutsWithin,
  planWidgetsMove,
  resolveWidths,
  rootLayoutId,
  widgetWidthSubdivisions,
  defaultWidgetName,
  pagesOf,
  withFreshIds,
  withFreshPage,
  ButtonWidget,
  CarouselWidget,
  TabsWidget,
  Widget,
  WidgetRow,
  WorkspaceDataModel,
} from '@/workspace'

/** A widget of no particular kind, named after its ID so a layout reads as what it holds. */
function widget(id: string, width: number = widgetWidthSubdivisions): Widget {
  return { id, type: 'logs', name: id, width, restricted: false, filter: {} } as Widget
}

function row(id: string, ...widgets: Widget[]): WidgetRow {
  return { id, height: 250, collapsed: false, widgets }
}

function carousel(id: string, slides: { id: string; layout: WidgetRow[] }[]): CarouselWidget {
  return {
    id,
    type: 'carousel',
    name: id,
    width: widgetWidthSubdivisions,
    restricted: false,
    frameless: false,
    interval: 15,
    autoplay: false,
    slides: slides.map((slide) => ({ id: slide.id, name: '', layout: slide.layout })),
  }
}

function tabs(id: string, pages: { id: string; layout: WidgetRow[] }[]): TabsWidget {
  return {
    id,
    type: 'tabs',
    name: id,
    width: widgetWidthSubdivisions,
    restricted: false,
    frameless: false,
    tabs: pages.map((page) => ({ id: page.id, name: '', layout: page.layout })),
  }
}

/** The layouts a plan settles on, as rows of widget IDs, which is what a plan actually decides. */
function shapeOf(plan: { layouts: Record<string, { widgets: string[] }[]> } | null) {
  if (plan == null) {
    return null
  }

  return Object.fromEntries(
    Object.entries(plan.layouts).map(([id, rows]) => [id, rows.map((current) => current.widgets)])
  )
}

function layoutsOf(root: WidgetRow[]): Map<string, WidgetRow[]> {
  return new Map(collectLayouts(root, () => {}).map((layout) => [layout.id, layout.rows]))
}

describe('resolveWidths', () => {
  it('leaves a row that already fills its width alone', () => {
    expect(resolveWidths([60, 60])).toEqual([60, 60])
  })

  it('spreads the difference over every width by default', () => {
    expect(resolveWidths([120, 120])).toEqual([60, 60])
  })

  it('holds the named widths and takes the difference from the rest', () => {
    expect(resolveWidths([60, 60, 60], 0)).toEqual([60, 30, 30])
  })

  it('takes the difference only from what follows, when asked to', () => {
    expect(resolveWidths([30, 60, 60], 1, 'after')).toEqual([30, 60, 30])
  })

  it('has nothing to say about an empty row', () => {
    expect(resolveWidths([])).toEqual([])
  })
})

describe('pagesOf', () => {
  it('finds none on a widget that holds no layouts', () => {
    expect(pagesOf(widget('a'))).toEqual([])
  })

  it('finds the slides of a carousel', () => {
    const holder = carousel('holder', [{ id: 's1', layout: [] }])

    expect(pagesOf(holder).map((page) => page.id)).toEqual(['s1'])
  })

  it('finds the pages of a tab strip', () => {
    const holder = tabs('holder', [
      { id: 't1', layout: [] },
      { id: 't2', layout: [] },
    ])

    expect(pagesOf(holder).map((page) => page.id)).toEqual(['t1', 't2'])
  })
})

describe('collectLayouts', () => {
  it('names the workspace layout first', () => {
    const root = [row('r1', widget('a'))]

    expect(collectLayouts(root, () => {}).map((layout) => layout.id)).toEqual([rootLayoutId])
  })

  it('finds the layouts a carousel carries, however deep they are', () => {
    const inner = carousel('inner', [{ id: 'inner-1', layout: [row('r3', widget('c'))] }])
    const outer = carousel('outer', [
      { id: 'outer-1', layout: [row('r2', widget('b'), inner)] },
      { id: 'outer-2', layout: [] },
    ])

    expect(collectLayouts([row('r1', outer)], () => {}).map((layout) => layout.id)).toEqual([
      rootLayoutId,
      'outer-1',
      'inner-1',
      'outer-2',
    ])
  })

  it('finds the pages of a tab strip the same way it finds a slide', () => {
    const holder = tabs('holder', [
      { id: 't1', layout: [row('r2', widget('b'))] },
      { id: 't2', layout: [] },
    ])

    expect(collectLayouts([row('r1', holder)], () => {}).map((layout) => layout.id)).toEqual([
      rootLayoutId,
      't1',
      't2',
    ])
  })

  it('writes a slide back where it came from', () => {
    const holder = carousel('holder', [{ id: 's1', layout: [row('r2', widget('b'))] }])

    const layout = collectLayouts([row('r1', holder)], () => {}).find(
      (current) => current.id === 's1'
    )
    layout?.set([row('r9', widget('z'))])

    expect(holder.slides[0].layout.map((current) => current.id)).toEqual(['r9'])
  })
})

describe('layoutsWithin', () => {
  it('finds nothing inside a widget that holds no layouts', () => {
    expect([...layoutsWithin([widget('a')])]).toEqual([])
  })

  it('finds the layouts a tab strip carries', () => {
    const holder = tabs('holder', [
      { id: 't1', layout: [] },
      { id: 't2', layout: [] },
    ])

    expect([...layoutsWithin([holder])].sort()).toEqual(['t1', 't2'])
  })

  it('finds every layout a carousel carries, including nested ones', () => {
    const inner = carousel('inner', [{ id: 'inner-1', layout: [] }])
    const outer = carousel('outer', [{ id: 'outer-1', layout: [row('r1', inner)] }])

    expect([...layoutsWithin([outer])].sort()).toEqual(['inner-1', 'outer-1'])
  })
})

describe('withFreshIds', () => {
  it('renames the widget', () => {
    expect(withFreshIds(widget('a')).id).not.toBe('a')
  })

  it('renames the slides a carousel carries and everything on them', () => {
    const original = carousel('outer', [{ id: 'outer-1', layout: [row('r1', widget('a'))] }])
    const copy = withFreshIds(original) as CarouselWidget

    expect(copy.slides[0].id).not.toBe('outer-1')
    expect(copy.slides[0].layout[0].id).not.toBe('r1')
    expect(copy.slides[0].layout[0].widgets[0].id).not.toBe('a')
  })

  it('renames the pages of a tab strip and everything on them', () => {
    const original = tabs('holder', [{ id: 't1', layout: [row('r1', widget('a'))] }])
    const copy = withFreshIds(original) as TabsWidget

    expect(copy.tabs[0].id).not.toBe('t1')
    expect(copy.tabs[0].layout[0].widgets[0].id).not.toBe('a')
  })

  it('leaves the widget it copied untouched', () => {
    const original = carousel('outer', [{ id: 'outer-1', layout: [row('r1', widget('a'))] }])
    withFreshIds(original)

    expect(original.slides[0].id).toBe('outer-1')
    expect(original.slides[0].layout[0].widgets[0].id).toBe('a')
  })
})

describe('withFreshPage', () => {
  it('renames the page and everything on it', () => {
    const original = { id: 'p1', name: 'Overview', layout: [row('r1', widget('a'))] }
    const copy = withFreshPage(original)

    expect(copy.id).not.toBe('p1')
    expect(copy.layout[0].id).not.toBe('r1')
    expect(copy.layout[0].widgets[0].id).not.toBe('a')
  })

  it('keeps the name it was given, which is not a name anything answers to', () => {
    expect(withFreshPage({ id: 'p1', name: 'Overview', layout: [] }).name).toBe('Overview')
  })

  it('leaves the page it copied untouched', () => {
    const original = { id: 'p1', name: '', layout: [row('r1', widget('a'))] }
    withFreshPage(original)

    expect(original.layout[0].widgets[0].id).toBe('a')
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

describe('planWidgetsMove', () => {
  it('says nothing about widgets no layout holds', () => {
    expect(planWidgetsMove(layoutsOf([row('r1', widget('a'))]), ['nowhere'], null)).toBeNull()
  })

  it('plans the removal alone when nowhere has been chosen', () => {
    const layouts = layoutsOf([row('r1', widget('a'), widget('b')), row('r2', widget('c'))])

    expect(shapeOf(planWidgetsMove(layouts, ['a'], null))).toEqual({ root: [['b'], ['c']] })
  })

  it('drops a row the move empties', () => {
    const layouts = layoutsOf([row('r1', widget('a')), row('r2', widget('b'))])

    expect(shapeOf(planWidgetsMove(layouts, ['a'], null))).toEqual({ root: [['b']] })
  })

  it('joins a row it is dropped into', () => {
    const layouts = layoutsOf([row('r1', widget('a')), row('r2', widget('b'))])
    const plan = planWidgetsMove(layouts, ['a'], { layout: rootLayoutId, row: 0, column: 1 })

    expect(shapeOf(plan)).toEqual({ root: [['b', 'a']] })
  })

  it('opens a row of its own where a seam was chosen', () => {
    const layouts = layoutsOf([row('r1', widget('a'), widget('b'))])
    const plan = planWidgetsMove(layouts, ['a'], { layout: rootLayoutId, row: 1, column: null })

    expect(shapeOf(plan)).toEqual({ root: [['b'], ['a']] })
  })

  it('shares a joined row out evenly', () => {
    const layouts = layoutsOf([row('r1', widget('a')), row('r2', widget('b'))])
    const plan = planWidgetsMove(layouts, ['a'], { layout: rootLayoutId, row: 0, column: 1 })

    expect(plan == null ? null : ['b', 'a'].map((id) => plan.widths[id])).toEqual([60, 60])
  })

  it('carries a widget into a carousel slide, naming both layouts', () => {
    const holder = carousel('holder', [{ id: 's1', layout: [row('r2', widget('b'))] }])
    const layouts = layoutsOf([row('r1', holder), row('r3', widget('a'))])
    const plan = planWidgetsMove(layouts, ['a'], { layout: 's1', row: 0, column: 1 })

    expect(shapeOf(plan)).toEqual({ root: [['holder']], s1: [['b', 'a']] })
  })

  it('carries a widget back out of a slide into the workspace', () => {
    const holder = carousel('holder', [{ id: 's1', layout: [row('r2', widget('b'), widget('c'))] }])
    const layouts = layoutsOf([row('r1', holder)])
    const plan = planWidgetsMove(layouts, ['b'], { layout: rootLayoutId, row: 1, column: null })

    expect(shapeOf(plan)).toEqual({ root: [['holder'], ['b']], s1: [['c']] })
  })

  it('refuses to put a carousel onto a slide of its own', () => {
    const holder = carousel('holder', [{ id: 's1', layout: [row('r2', widget('b'))] }])
    const layouts = layoutsOf([row('r1', holder)])

    expect(planWidgetsMove(layouts, ['holder'], { layout: 's1', row: 0, column: 1 })).toBeNull()
  })

  it('refuses to put a tab strip onto a page of its own', () => {
    const holder = tabs('holder', [{ id: 't1', layout: [row('r2', widget('b'))] }])
    const layouts = layoutsOf([row('r1', holder)])

    expect(planWidgetsMove(layouts, ['holder'], { layout: 't1', row: 0, column: 1 })).toBeNull()
  })

  it('carries a widget into a tab strip page', () => {
    const holder = tabs('holder', [{ id: 't1', layout: [row('r2', widget('b'))] }])
    const layouts = layoutsOf([row('r1', holder), row('r3', widget('a'))])
    const plan = planWidgetsMove(layouts, ['a'], { layout: 't1', row: 0, column: 1 })

    expect(shapeOf(plan)).toEqual({ root: [['holder']], t1: [['b', 'a']] })
  })

  it('refuses a row that is not there to drop into', () => {
    const layouts = layoutsOf([row('r1', widget('a'), widget('b'))])

    expect(planWidgetsMove(layouts, ['a'], { layout: rootLayoutId, row: 9, column: 0 })).toBeNull()
  })
})

describe('a stored button widget', () => {
  /** The widgets a stored workspace holds, once it has been read the way the app reads one. */
  function loaded(...widgets: unknown[]): Widget[] {
    const data = WorkspaceDataModel.parse({
      layout: [{ id: 'r1', height: 250, collapsed: false, widgets }],
    })

    return data.layout[0].widgets
  }

  function buttonsOf(widget: Widget): ButtonWidget['buttons'] {
    return (widget as ButtonWidget).buttons
  }

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

    expect(buttonsOf(upgraded)).toHaveLength(1)
    expect(buttonsOf(upgraded)[0].action).toBe('restart')
    expect(buttonsOf(upgraded)[0].label).toBe('Restart')
    expect(buttonsOf(upgraded)[0].arguments).toEqual({ force: true })
  })

  it('holds no buttons when nothing was ever made of it', () => {
    const [upgraded] = loaded({ id: 'w1', type: 'button', name: '', arguments: {} })

    expect(buttonsOf(upgraded)).toEqual([])
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

  it('comes back asking for its arguments and asking nothing else', () => {
    const [upgraded] = loaded({ id: 'w1', type: 'button', name: '', action: 'restart' })

    expect(buttonsOf(upgraded)[0].locked).toBe(false)
    expect(buttonsOf(upgraded)[0].confirm).toBe(false)
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
    buttonsOf(first)[0].confirm = true

    // The trip a workspace makes every time it is saved and opened again.
    const [second] = loaded(JSON.parse(JSON.stringify(first)))
    const button = buttonsOf(second)[0]

    expect(buttonsOf(second)).toHaveLength(1)
    expect(button.id).toBe(buttonsOf(first)[0].id)
    expect(button.address?.toString()).toBe('@engine.thing')
    expect(button.action).toBe('restart')
    expect(button.arguments).toEqual({ force: true })
    expect(button.confirm).toBe(true)
    expect(button.locked).toBe(false)
  })

  it('is left alone once it holds buttons of its own', () => {
    const [upgraded] = loaded({
      id: 'w1',
      type: 'button',
      name: '',
      buttons: [{ id: 'b1', action: 'one' }, { id: 'b2', action: 'two' }],
      action: 'legacy',
    })

    expect(buttonsOf(upgraded).map((button) => button.action)).toEqual(['one', 'two'])
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

    const inside = pagesOf(upgraded)[0].layout[0].widgets[0]
    expect(buttonsOf(inside).map((button) => button.action)).toEqual(['restart'])
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

    const inside = pagesOf(upgraded)[0].layout[0].widgets[0]
    expect(buttonsOf(inside).map((button) => button.action)).toEqual(['restart'])
  })

  it('wears no frame of its own, unlike a widget that is a view of something', () => {
    const [button, chart] = loaded(
      { id: 'w1', type: 'button', name: '' },
      { id: 'w2', type: 'chart', name: 'Chart' }
    )

    expect(button.frameless).toBe(true)
    expect(chart.frameless).toBe(false)
  })
})
