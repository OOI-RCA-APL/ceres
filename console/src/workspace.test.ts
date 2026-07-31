import { describe, expect, it } from 'vitest'

import {
  collectLayouts,
  layoutsWithin,
  planWidgetsMove,
  resolveWidths,
  rootLayoutId,
  widgetWidthSubdivisions,
  withFreshIds,
  CarouselWidget,
  Widget,
  WidgetRow,
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
    interval: 15,
    autoplay: false,
    slides: slides.map((slide) => ({ id: slide.id, name: '', layout: slide.layout })),
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

  it('leaves the widget it copied untouched', () => {
    const original = carousel('outer', [{ id: 'outer-1', layout: [row('r1', widget('a'))] }])
    withFreshIds(original)

    expect(original.slides[0].id).toBe('outer-1')
    expect(original.slides[0].layout[0].widgets[0].id).toBe('a')
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

  it('refuses a row that is not there to drop into', () => {
    const layouts = layoutsOf([row('r1', widget('a'), widget('b'))])

    expect(planWidgetsMove(layouts, ['a'], { layout: rootLayoutId, row: 9, column: 0 })).toBeNull()
  })
})
