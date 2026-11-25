import { defineAsyncComponent } from 'vue'

import icons from '@/icons'
import {
  emptyPage,
  isPagesWidget,
  type LayoutArrange,
  pagesOf,
  type PagesWidgetType,
  type SectionWidget,
  UnknownWidgetModel,
  type Widget,
  widgetModels,
  type WidgetRow,
  type WidgetRowHeight,
  WidgetRowModel,
  type WidgetType,
  withPages,
} from '@/workspace/models'

const defaultMinHeight = 150
const defaultPaddingClass = 'p-2'

type WidgetOptionsInput = {
  minHeight?: number
  framelessMinHeight?: number
  initialHeight?: number
  paddingClass?: string | string[]
  fullHeight?: boolean
  fitsContent?: boolean
  fitsWidth?: boolean
  bare?: boolean
  reloadOnThemeChange?: boolean
  opensSettingsWhenAdded?: boolean
}

type WidgetOptions = {
  minHeight: number
  /** The least height without the frame's header and padding, at most `minHeight`. */
  framelessMinHeight: number
  /** The height a row created for this widget opens at, at least `minHeight`. */
  initialHeight: number
  paddingClass: string | string[]
  fullHeight: boolean
  /** Whether the widget's height follows what it shows, so a row sized to its contents can hold
  it. A widget filling whatever height it is given, such as a chart, has no height of its own. */
  fitsContent: boolean
  /** Whether the widget's width follows what it shows too, which a flex layout needs. */
  fitsWidth: boolean
  /** Whether the widget is drawn as its content alone, with no card, header or frame handle. Its
  content starts a drag and carries the widget's menu itself. */
  bare: boolean
  reloadOnThemeChange: boolean
  /** Whether adding the widget opens its settings, for a widget that shows nothing until it is
  told what to show. */
  opensSettingsWhenAdded: boolean
}

function widgetOptions(options: WidgetOptionsInput): WidgetOptions {
  return {
    minHeight: options.minHeight ?? defaultMinHeight,
    framelessMinHeight: options.framelessMinHeight ?? options.minHeight ?? defaultMinHeight,
    initialHeight: options.initialHeight ?? options.minHeight ?? defaultMinHeight,
    paddingClass: options.paddingClass ?? defaultPaddingClass,
    fullHeight: options.fullHeight ?? true,
    fitsContent: options.fitsContent ?? false,
    fitsWidth: options.fitsWidth ?? false,
    bare: options.bare ?? false,
    reloadOnThemeChange: options.reloadOnThemeChange ?? false,
    opensSettingsWhenAdded: options.opensSettingsWhenAdded ?? false,
  }
}

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
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-procedures.vue')),
    options: widgetOptions({
      fullHeight: false,
      fitsContent: true,
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
      opensSettingsWhenAdded: true,
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
      opensSettingsWhenAdded: true,
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
  files: {
    type: 'files',
    name: 'Files View',
    model: widgetModels.files,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-files.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/c-workspace-widget-files-settings.vue'),
    ),
    options: widgetOptions({
      minHeight: 200,
      initialHeight: 320,
      paddingClass: [],
    }),
  },
  section: {
    type: 'section',
    name: 'Section',
    model: widgetModels.section,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-section.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/c-workspace-widget-section-settings.vue'),
    ),
    options: widgetOptions({
      // As short as a header over one line of buttons, which a section laying them out holds.
      minHeight: 75,
      framelessMinHeight: 45,
      initialHeight: 150,
      paddingClass: [],
      fitsContent: true,
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
      fitsContent: true,
    }),
  },
  carousel: {
    type: 'carousel',
    name: 'Carousel',
    model: widgetModels.carousel,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-carousel.vue')),
    // No settings dialog. Its slides are arranged in place and its behavior is set from the
    // control band under them. Its slides are stacked out of flow to travel sideways, so it has
    // no height of its own to fit to.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  button: {
    type: 'button',
    name: 'Button',
    model: widgetModels.button,
    component: defineAsyncComponent(() => import('@/components/c-workspace-widget-button.vue')),
    // No settings dialog of the workspace's. The button opens its own from its menu.
    options: widgetOptions({
      // One 32px button and the 10px of menu dots hanging under it, rounded to the 5px step the
      // row's resize handle moves in.
      minHeight: 45,
      fullHeight: false,
      paddingClass: [],
      fitsContent: true,
      fitsWidth: true,
      bare: true,
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
    fitsContent: true,
  }),
} as const

export type WidgetInfo = (typeof widgetInfos)[keyof typeof widgetInfos] | typeof unknownWidgetInfo
export type WidgetComponent = (typeof widgetInfos)[WidgetType]['component']

export function getWidgetInfo(type: WidgetType): WidgetInfo {
  // A stored widget can carry a kind this console has no model for, whatever its type claims.
  return (widgetInfos as Partial<Record<string, WidgetInfo>>)[type] ?? unknownWidgetInfo
}

/** The least height of a row holding `widget`, lower without the frame's header and padding. */
export function widgetMinHeight(widget: Widget): number {
  const { options } = getWidgetInfo(widget.type)
  return widget.frameless ? options.framelessMinHeight : options.minHeight
}

/** Whether `widget` takes its height from what it shows, which a row sized to its contents
needs. A widget that does not gets its opening height as a floor in such a row. */
export function fitsContent(widget: Widget): boolean {
  return getWidgetInfo(widget.type).options.fitsContent
}

/** Whether `widget` takes its width from what it shows, which a flex layout needs. */
export function fitsWidth(widget: Widget): boolean {
  return getWidgetInfo(widget.type).options.fitsWidth
}

/** Whether a layout arranged as `arrange` can hold every one of `widgets`. A flex layout holds
only widgets sized by their contents, since it gives them no share of its width. */
export function arrangeAccepts(arrange: LayoutArrange, widgets: Iterable<Widget>): boolean {
  return arrange === 'rows' || [...widgets].every(fitsWidth)
}

/** The widget kinds a layout arranged as `arrange` offers to add, in menu order. */
export function addableWidgetInfos(
  arrange: LayoutArrange,
): (typeof widgetInfos)[keyof typeof widgetInfos][] {
  return Object.values(widgetInfos).filter((info) => arrange === 'rows' || info.options.fitsWidth)
}

/** The height a row opened for `widgets` starts at: sized to its contents when every widget
fits them, else as tall as the tallest asks to open at. */
export function openedRowHeight(widgets: Widget[]): WidgetRowHeight {
  if (widgets.every(fitsContent)) {
    return 'auto'
  }

  return Math.max(...widgets.map((widget) => getWidgetInfo(widget.type).options.initialHeight))
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

  // A widget that holds pages begins with one since one with no pages has no layout to drag or
  // paste widgets into.
  if (isPagesWidget(widget) && pagesOf(widget).length === 0) {
    return withPages(widget, [emptyPage()])
  }

  return widget
}

/** A frameless section laying `buttons` out side by side, the way a set of related actions is
usually wanted. */
export function createButtonBar(buttons: Widget[]): Widget {
  const section = createWidget('section') as SectionWidget
  return {
    ...section,
    frameless: true,
    expand: 'none',
    pages: [{ ...emptyPage('flex'), layout: [openedRowFor(buttons)] }],
  }
}

/** Every pages-widget kind, in the order menus offer them. */
export const pagesWidgetTypes = ['section', 'tabs', 'carousel'] as const satisfies PagesWidgetType[]

/** The icon a menu shows beside each pages-widget kind. */
export const pagesWidgetIcons: Record<PagesWidgetType, string> = {
  tabs: icons.tab,
  carousel: icons.carousel,
  section: icons.section,
}

/** The pages-widget kinds `widget` can be turned into, in menu order. None for a widget that
holds no pages. */
export function pagesWidgetConversions(widget: Widget): PagesWidgetType[] {
  if (!isPagesWidget(widget)) {
    return []
  }

  return pagesWidgetTypes.filter((kind) => kind !== widget.type)
}

/** A "Convert To" menu item for each kind `widget` can be turned into, handing the converted
widget to `replace`. Shared by the widget's own menu and the menus on its strip or controls. */
export function pagesWidgetConversionItems(widget: Widget, replace: (converted: Widget) => void) {
  return pagesWidgetConversions(widget).map((kind) => ({
    label: `Convert To ${widgetInfos[kind].name}`,
    icon: pagesWidgetIcons[kind],
    onSelect: () => {
      const converted = convertedPagesWidget(widget, kind)
      if (converted != null) {
        replace(converted)
      }
    },
  }))
}

/** The widget's pages under another pages-widget kind, in the same place.

Returns null for a widget that holds no pages or is already of that kind. The pages carry across
with their names, layouts, and IDs, except that a section folds them into its one, and how the
leftover height is spread carries across too.
*/
export function convertedPagesWidget(widget: Widget, to: PagesWidgetType): Widget | null {
  if (!isPagesWidget(widget) || widget.type === to) {
    return null
  }

  const converted = createWidget(to) as Widget & { expand: unknown; shrink: boolean }
  converted.expand = widget.expand
  converted.shrink = widget.shrink

  // A name that is still one kind's default was never chosen so the other kind's default
  // replaces it.
  if (widget.name !== defaultWidgetName(widget.type)) {
    converted.name = widget.name
  }

  return withPages(converted, pagesOf(widget))
}

/** A row opened for arriving widgets, at the height `openedRowHeight` gives them. */
export function openedRowFor(widgets: Widget[]): WidgetRow {
  return WidgetRowModel.parse({ widgets, height: openedRowHeight(widgets) })
}
