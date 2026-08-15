import { v7 } from 'uuid'
import { defineAsyncComponent } from 'vue'

import {
  pagesOf,
  UnknownWidgetModel,
  type Widget,
  widgetModels,
  type WidgetRow,
  WidgetRowModel,
  type WidgetType,
  withPages,
} from '@/workspace/models'

const defaultMinHeight = 150
const defaultPaddingClass = 'p-2'

type WidgetOptionsInput = {
  minHeight?: number
  initialHeight?: number
  paddingClass?: string | string[]
  fullHeight?: boolean
  reloadOnThemeChange?: boolean
}

type WidgetOptions = {
  minHeight: number
  /** The height a row created for this widget opens at, at least `minHeight`. */
  initialHeight: number
  paddingClass: string | string[]
  fullHeight: boolean
  reloadOnThemeChange: boolean
}

function widgetOptions(options: WidgetOptionsInput): WidgetOptions {
  return {
    minHeight: options.minHeight ?? defaultMinHeight,
    initialHeight: options.initialHeight ?? options.minHeight ?? defaultMinHeight,
    paddingClass: options.paddingClass ?? defaultPaddingClass,
    fullHeight: options.fullHeight ?? true,
    reloadOnThemeChange: options.reloadOnThemeChange ?? false,
  }
}

// Stands in for every widget kind whose real component lands in a later slice.
const pendingComponent = defineAsyncComponent(
  () => import('@/components/c-workspace-widget-pending.vue'),
)

export const widgetInfos = {
  messages: {
    type: 'messages',
    name: 'Messages View',
    model: widgetModels.messages,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-messages.vue')),
    options: widgetOptions({}),
  },
  particles: {
    type: 'particles',
    name: 'Particles View',
    model: widgetModels.particles,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-particles.vue')),
    options: widgetOptions({}),
  },
  alerts: {
    type: 'alerts',
    name: 'Alerts View',
    model: widgetModels.alerts,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-alerts.vue')),
    options: widgetOptions({}),
  },
  logs: {
    type: 'logs',
    name: 'Logs View',
    model: widgetModels.logs,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-logs.vue')),
    options: widgetOptions({}),
  },
  procedures: {
    type: 'procedures',
    name: 'Procedures View',
    model: widgetModels.procedures,
    component: pendingComponent,
    options: widgetOptions({
      fullHeight: false,
    }),
  },
  chart: {
    type: 'chart',
    name: 'Chart',
    model: widgetModels.chart,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-chart.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/c-workspace-widget-chart-settings.vue'),
    ),
    options: widgetOptions({
      minHeight: 200,
      paddingClass: ['py-2', 'pr-4'],
      reloadOnThemeChange: true,
    }),
  },
  meter: {
    type: 'meter',
    name: 'Meter',
    model: widgetModels.meter,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-meter.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/c-workspace-widget-meter-settings.vue'),
    ),
    options: widgetOptions({
      minHeight: 50,
      initialHeight: 60,
      paddingClass: [],
    }),
  },
  video: {
    type: 'video',
    name: 'Video',
    model: widgetModels.video,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-video.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/c-workspace-widget-video-settings.vue'),
    ),
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  tabs: {
    type: 'tabs',
    name: 'Tabs',
    model: widgetModels.tabs,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-tabs.vue')),
    // No settings dialog. Its pages are arranged on the strip itself.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  carousel: {
    type: 'carousel',
    name: 'Carousel',
    model: widgetModels.carousel,
    component: pendingComponent,
    // No settings dialog. Its slides are arranged in place and its behavior is set from the
    // control band under them.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  controls: {
    type: 'controls',
    name: 'Controls',
    model: widgetModels.controls,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-controls.vue')),
    // No settings dialog. Each control is configured from the control itself.
    options: widgetOptions({
      minHeight: 90,
      fullHeight: false,
    }),
  },
} as const

// Covers every kind `widgetInfos` does not. Kept outside it so no menu offers creating one.
const unknownWidgetInfo = {
  type: 'unknown',
  name: 'Unknown Widget',
  model: UnknownWidgetModel,
  component: defineAsyncComponent(() => import('@/components/c-workspace-widget-unknown.vue')),
  options: widgetOptions({
    fullHeight: false,
  }),
} as const

export type WidgetInfo = (typeof widgetInfos)[keyof typeof widgetInfos] | typeof unknownWidgetInfo
export type WidgetComponent = (typeof widgetInfos)[WidgetType]['component']

export function getWidgetInfo(type: WidgetType): WidgetInfo {
  // A stored widget can carry a kind this console has no model for, whatever its type claims.
  return (widgetInfos as Partial<Record<string, WidgetInfo>>)[type] ?? unknownWidgetInfo
}

/** The default name for a widget of `type`.

Changing a widget's kind compares against this to tell a chosen name from an inherited one.
*/
export function defaultWidgetName(type: WidgetType): string {
  return createWidget(type).name
}

/** Build a widget of `type`, with the defaults its own model declares.

The cast is required because the widget shape is recursive and the compiler cannot infer it.
*/
export function createWidget(type: WidgetType): Widget {
  const widget = widgetInfos[type].model.parse({ type }) as Widget

  // A carousel or a tab strip begins with a page since one with no pages has no layout to drag
  // or paste widgets into.
  if ((widget.type === 'carousel' || widget.type === 'tabs') && pagesOf(widget).length === 0) {
    return withPages(widget, [{ id: v7(), name: '', layout: [] }])
  }

  return widget
}

/** The widget's pages under the other pages-widget kind, a carousel becomes tabs and back.

Returns null for a widget that holds no pages. The pages carry across untouched, keeping their
names, layouts, and IDs.
*/
export function convertedPagesWidget(widget: Widget): Widget | null {
  if (widget.type !== 'carousel' && widget.type !== 'tabs') {
    return null
  }

  const converted = createWidget(widget.type === 'carousel' ? 'tabs' : 'carousel')

  // A name that is still one kind's default was never chosen so the other kind's default
  // replaces it.
  if (widget.name !== defaultWidgetName(widget.type)) {
    converted.name = widget.name
  }

  return withPages(converted, pagesOf(widget))
}

/** A row opened for arriving widgets, as tall as the tallest of them asks to open at. */
export function openedRowFor(widgets: Widget[]): WidgetRow {
  return WidgetRowModel.parse({
    widgets,
    height: Math.max(...widgets.map((widget) => getWidgetInfo(widget.type).options.initialHeight)),
  })
}
