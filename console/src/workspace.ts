import { useQuery } from '@tanstack/vue-query'
import { useEventListener } from '@vueuse/core'
import { debounce, omit, orderBy } from 'lodash-es'
import { defineStore } from 'pinia'
import { copyToClipboard, exportFile as download } from 'quasar'
import { v7 } from 'uuid'
import {
  computed,
  defineAsyncComponent,
  inject,
  MaybeRef,
  onScopeDispose,
  provide,
  reactive,
  readonly,
  unref,
  watch,
  watchEffect,
} from 'vue'
import Zod from 'zod'

import { useAccess } from '@/api/access'
import {
  Address,
  AddressModel,
  AddressSelector,
  AddressSelectorModel,
  engineRoot,
} from '@/api/address'
import { AlertFilterModel } from '@/api/alerts'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ProcedureTypeModel } from '@/api/components'
import { LogEntryFilterModel } from '@/api/logs'
import { MessageFilterModel } from '@/api/messages'
import { ParticleFilterModel } from '@/api/particles'
import { DateTimeModel } from '@/api/shared'
import { Failure } from '@/errors'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { workspaceInjectionKey } from '@/symbols'
import { workspaceQueryKey } from '@/tabs'
import { deepClone, isStructurallyEqual, safeArrayOf, selectFile } from '@/utilities'

export type BaseWidget = Zod.infer<typeof BaseWidgetModel>
const BaseWidgetModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  name: Zod.string(),
  // Fraction of row width out of 120, not pixels.
  width: Zod.number().catch(() => widgetWidthSubdivisions),
  restricted: Zod.boolean().catch(false),

  // Whether the widget renders without a card and header around it. Its content is all that
  // shows, and the drag handle appears over it on hover.
  frameless: Zod.boolean().catch(false),
})

export type MessageDataDisplay = Zod.infer<typeof MessageDataDisplayModel>
export const MessageDataDisplayModel = Zod.enum(['default', 'hex', 'binary']).catch('default')

export type MessagesWidget = Zod.infer<typeof MessagesWidgetModel>
export const MessagesWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('messages'),
  name: Zod.string().catch('Messages'),
  filter: MessageFilterModel.catch(() => ({})),
  dataDisplay: MessageDataDisplayModel,
  commandAddress: AddressModel.nullish(),
  commandConnection: Zod.string().nullish(),
  commandText: Zod.string().catch(''),
  commandHistory: Zod.string()
    .array()
    .catch(() => []),
  commandHistoryIndex: Zod.number().nullish().catch(undefined),
})

export type ParticlesWidget = Zod.infer<typeof ParticlesWidgetModel>
export const ParticlesWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('particles'),
  name: Zod.string().catch('Particles'),
  filter: ParticleFilterModel.catch(() => ({})),
})

export type AlertsWidget = Zod.infer<typeof AlertsWidgetModel>
export const AlertsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('alerts'),
  name: Zod.string().catch('Alerts'),
  filter: AlertFilterModel.catch(() => ({})),
})

export type LogsWidget = Zod.infer<typeof LogsWidgetModel>
export const LogsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('logs'),
  name: Zod.string().catch('Logs'),
  filter: LogEntryFilterModel.catch(() => ({})),
})

export type ProceduresWidget = Zod.infer<typeof ProceduresWidgetModel>
export const ProceduresWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('procedures'),
  name: Zod.string().catch('Procedures'),
  procedureAddress: AddressModel.nullish(),
  procedureType: ProcedureTypeModel.catch('action'),
  procedureName: Zod.string().nullish(),
})

export type ChartWidgetDisplay = Zod.infer<typeof ChartWidgetDisplayModel>
export const ChartWidgetDisplayModel = Zod.enum(['line', 'scatter', 'bar'])

export type ChartWidgetSeries = Zod.infer<typeof ChartWidgetSeriesModel>
export const ChartWidgetSeriesModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  field: Zod.string().nullish(),
  label: Zod.string().nullish(),
})

export type ChartWidgetParticle = Zod.infer<typeof ChartWidgetParticleModel>
export const ChartWidgetParticleModel = Zod.object({
  address: AddressSelectorModel.nullish(),
  type: Zod.string().nullish(),
  series: safeArrayOf(ChartWidgetSeriesModel),
})

export type ChartWidget = Zod.infer<typeof ChartWidgetModel>
export const ChartWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('chart'),
  name: Zod.string().catch('Chart'),
  display: ChartWidgetDisplayModel.catch('line'),
  unit: Zod.string().nullish(),
  after: DateTimeModel.nullish(),
  timespan: Zod.union([Zod.number(), Zod.string()])
    .nullish()
    .catch(60 * 60),
  particles: safeArrayOf(ChartWidgetParticleModel),
})

export type TextWeight = Zod.infer<typeof TextWeightModel>
export const TextWeightModel = Zod.enum(['slim', 'normal', 'bold'])

export type ValueWidget = Zod.infer<typeof ValueWidgetModel>
export const ValueWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('value'),
  name: Zod.string().catch('Value'),
  particleAddress: AddressSelectorModel.nullish(),
  particleType: Zod.string().nullish(),
  particleField: Zod.string().nullish(),
  fontSize: Zod.number().min(1).max(60).nullish(),
  fontWeight: TextWeightModel.default('normal').catch('normal'),
  prefix: Zod.string().nullish(),
  suffix: Zod.string().nullish(),
})

export type VideoWidget = Zod.infer<typeof VideoWidgetModel>
export const VideoWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('video'),
  name: Zod.string().catch('Video'),
  query: Zod.string().nullish(),
  autoplay: Zod.boolean().default(true).catch(true),
  startMuted: Zod.boolean().default(true).catch(true),
  showControls: Zod.boolean().default(true).catch(true),
})

export type Color = Zod.infer<typeof ColorModel>
export const ColorModel = Zod.enum(['primary', 'positive', 'warning', 'negative'])

export type ButtonStyling = Zod.infer<typeof ButtonStylingModel>
export const ButtonStylingModel = Zod.enum(['flat', 'outlined'])

/** One action a button widget offers, and how pressing it behaves. */
export type ButtonAction = Zod.infer<typeof ButtonActionModel>
export const ButtonActionModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  label: Zod.string().nullish(),
  address: AddressModel.nullish(),
  action: Zod.string().nullish(),
  arguments: Zod.record(Zod.string(), Zod.any()).catch(() => ({})),
  color: ColorModel.nullish().catch(undefined),
  styling: ButtonStylingModel.nullish().catch(undefined),
  tooltip: Zod.string().nullish().catch(undefined),

  // Locked, pressing the button runs it with its stored arguments. Unlocked, pressing asks for
  // the action's arguments first, which is one more look before anything runs, so a fresh
  // button starts unlocked.
  locked: Zod.boolean().catch(false),

  /** Whether running the action asks first. On by default because a workspace button is easy
  to press by accident. */
  confirm: Zod.boolean().catch(true),
})

/** Controls offered side by side, laid out as a bar. Buttons are the one kind it holds so far. */
export type ControlsWidget = BaseWidget & {
  type: 'controls'
  buttons: ButtonAction[]
}

export const ControlsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('controls'),
  name: Zod.string().catch('Controls'),
  buttons: safeArrayOf(ButtonActionModel),
})

/** A controls widget in its legacy stored form, the single-action `button` widget.

The single-action fields are declared here rather than on `ControlsWidget` so the rest of the
app reaches an action only through `buttons`.
*/
type StoredButtonWidget = Omit<ControlsWidget, 'type'> & { type: 'button' } & Partial<
    Omit<ButtonAction, 'id' | 'locked' | 'confirm'>
  >

const StoredButtonWidgetModel = ControlsWidgetModel.extend({
  type: Zod.literal('button'),

  // The legacy single-action fields. Kept so a stored workspace still parses, and folded into
  // `buttons` by `upgradedWidget` on load.
  label: Zod.string().nullish(),
  address: AddressModel.nullish(),
  action: Zod.string().nullish(),
  arguments: Zod.record(Zod.string(), Zod.any()).nullish(),
  color: ColorModel.nullish().catch(undefined),
  styling: ButtonStylingModel.nullish().catch(undefined),
  tooltip: Zod.string().nullish().catch(undefined),
})

/** A named layout, as held by a carousel slide or a tab.

Written out rather than inferred because the types are mutually recursive.
*/
export type WidgetPage = {
  id: string
  name: string
  layout: WidgetRow[]
}

export const WidgetPageModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  name: Zod.string().catch(''),
  layout: safeArrayOf(Zod.lazy(() => WidgetRowModel)),
}) as unknown as Zod.ZodType<WidgetPage>

/** What a carousel calls its pages. */
export type CarouselSlide = WidgetPage

/** How a layout distributes height its rows have not claimed.

`last` gives it to the final row, `first` to the leading one, `even` shares it out, and `none`
leaves the rows at their dragged heights.
*/
export type LayoutExpand = Zod.infer<typeof LayoutExpandModel>
export const LayoutExpandModel = Zod.enum(['last', 'first', 'even', 'none'])

export type CarouselWidget = BaseWidget & {
  type: 'carousel'
  slides: WidgetPage[]

  /** How long each slide is shown, in seconds. */
  interval: number

  /** Whether it advances by itself instead of being stepped through by hand. */
  autoplay: boolean

  /** What the slides do with the height left over once their rows have taken theirs. */
  expand: LayoutExpand

  /** Whether rows may also be squeezed below their own heights to fit the slide. */
  shrink: boolean
}

export const CarouselWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('carousel'),
  name: Zod.string().catch('Carousel'),
  slides: safeArrayOf(WidgetPageModel),
  interval: Zod.number().min(1).max(3600).catch(15),
  // Off by default so a freshly added carousel does not start moving before it is set up.
  autoplay: Zod.boolean().catch(false),
  // The bottom of a slide is where empty space shows so the bottom row is given it.
  expand: LayoutExpandModel.catch('last'),
  // Off by default, squeezing rows below their dragged heights is opt-in.
  shrink: Zod.boolean().catch(false),
})

/** Pages shown one at a time, reached by name rather than in turn. */
export type TabsWidget = BaseWidget & {
  type: 'tabs'
  tabs: WidgetPage[]
  fill: boolean

  /** What the tabs do with the height left over once their rows have taken theirs. */
  expand: LayoutExpand

  /** Whether rows may also be squeezed below their own heights to fit the tab. */
  shrink: boolean
}

export const TabsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('tabs'),
  name: Zod.string().catch('Tabs'),
  tabs: safeArrayOf(WidgetPageModel),

  // Whether the tabs share the strip's width evenly rather than each taking only the room its
  // own name needs.
  fill: Zod.boolean().catch(false),
  // The bottom of a tab is where empty space shows so the bottom row is given it.
  expand: LayoutExpandModel.catch('last'),
  // Off by default, squeezing rows below their dragged heights is opt-in.
  shrink: Zod.boolean().catch(false),
})

export type Widget =
  | MessagesWidget
  | ParticlesWidget
  | AlertsWidget
  | LogsWidget
  | ProceduresWidget
  | ChartWidget
  | ValueWidget
  | VideoWidget
  | ControlsWidget
  | CarouselWidget
  | TabsWidget

/** A widget of a kind this console has no model for.

Its fields ride along unparsed so the next save does not delete a widget another console
version stored, and this console draws a placeholder for it.
*/
export const UnknownWidgetModel = BaseWidgetModel.extend({
  type: Zod.string(),
  name: Zod.string().catch(''),
}).passthrough()

export const WidgetModel = Zod.discriminatedUnion('type', [
  MessagesWidgetModel,
  ParticlesWidgetModel,
  AlertsWidgetModel,
  LogsWidgetModel,
  ProceduresWidgetModel,
  ChartWidgetModel,
  ValueWidgetModel,
  VideoWidgetModel,
  ControlsWidgetModel,
  // The controls widget's legacy stored kind, turned into `controls` by `upgradedWidget` on load.
  StoredButtonWidgetModel,
  CarouselWidgetModel,
  TabsWidgetModel,
]).or(UnknownWidgetModel) as unknown as Zod.ZodType<Widget>

export type WidgetType = Widget['type']
export type WidgetInfo = (typeof widgetInfos)[keyof typeof widgetInfos] | typeof unknownWidgetInfo
export type WidgetComponent = (typeof widgetInfos)[WidgetType]['component']

const defaultMinHeight = 150
const defaultPaddingClass = 'q-pa-sm'

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

type WidgetOptionsInput = {
  minHeight?: number
  paddingClass?: string | string[]
  fullHeight?: boolean
  reloadOnThemeChange?: boolean
}

type WidgetOptions = {
  minHeight: number
  paddingClass: string | string[]
  fullHeight: boolean
  reloadOnThemeChange: boolean
}

function widgetOptions(options: WidgetOptionsInput): WidgetOptions {
  return {
    minHeight: options.minHeight ?? defaultMinHeight,
    paddingClass: options.paddingClass ?? defaultPaddingClass,
    fullHeight: options.fullHeight ?? true,
    reloadOnThemeChange: options.reloadOnThemeChange ?? false,
  }
}

export const widgetInfos = {
  messages: {
    type: 'messages',
    name: 'Messages View',
    model: MessagesWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetMessages.vue')),
    options: widgetOptions({}),
  },
  particles: {
    type: 'particles',
    name: 'Particles View',
    model: ParticlesWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetParticles.vue')),
    options: widgetOptions({}),
  },
  alerts: {
    type: 'alerts',
    name: 'Alerts View',
    model: AlertsWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetAlerts.vue')),
    options: widgetOptions({}),
  },
  logs: {
    type: 'logs',
    name: 'Logs View',
    model: LogsWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetLogs.vue')),
    options: widgetOptions({}),
  },
  procedures: {
    type: 'procedures',
    name: 'Procedures View',
    model: ProceduresWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetProcedures.vue')),
    options: widgetOptions({
      fullHeight: false,
    }),
  },
  chart: {
    type: 'chart',
    name: 'Chart',
    model: ChartWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetChart.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/WorkspaceWidgetChartSettings.vue')
    ),
    options: widgetOptions({
      minHeight: 200,
      paddingClass: ['q-py-sm', 'q-pr-md'],
      reloadOnThemeChange: true,
    }),
  },
  value: {
    type: 'value',
    name: 'Value',
    model: ValueWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetValue.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/WorkspaceWidgetValueSettings.vue')
    ),
    options: widgetOptions({
      minHeight: 50,
      paddingClass: [],
    }),
  },
  video: {
    type: 'video',
    name: 'Video',
    model: VideoWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetVideo.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/WorkspaceWidgetVideoSettings.vue')
    ),
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  tabs: {
    type: 'tabs',
    name: 'Tabs',
    model: TabsWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetTabs.vue')),
    // No settings dialog. Its pages are arranged on the strip itself.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  carousel: {
    type: 'carousel',
    name: 'Carousel',
    model: CarouselWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetCarousel.vue')),
    // No settings dialog. Its slides are arranged in place and its behavior is set from the
    // control band under them.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  controls: {
    type: 'controls',
    name: 'Controls',
    model: ControlsWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetControls.vue')),
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
  component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetUnknown.vue')),
  options: widgetOptions({
    fullHeight: false,
  }),
} as const

/** Written out rather than inferred for the same reason as `WidgetPage`, the types are
mutually recursive. */
export type WidgetRow = {
  id: string
  height: number
  collapsed: boolean
  widgets: Widget[]
}

export const WidgetRowModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  height: Zod.number().catch(250),
  collapsed: Zod.boolean().catch(false),
  widgets: safeArrayOf(WidgetModel),
}) as unknown as Zod.ZodType<WidgetRow>

/** Widgets on the system clipboard, keeping their row structure.

The `ceres` marker tells a widget paste apart from any other text.
*/
export type WidgetClipboard = Zod.infer<typeof WidgetClipboardModel>
export const WidgetClipboardModel = Zod.object({
  ceres: Zod.literal('widgets'),
  // Upgraded on the way in because a copy can carry a legacy widget shape.
  rows: safeArrayOf(WidgetRowModel).transform(upgradedRows),
})

export type WorkspaceMeta = Zod.infer<typeof WorkspaceMetaModel>

/** Presentation state the console keeps alongside a workspace's contents.

The engine stores this without interpreting it so nothing here may affect how a workspace
behaves, only how the console chooses to display it.
*/
export const WorkspaceMetaModel = Zod.object({
  // Position among the workspaces scoped to the same component, ascending. Workspaces without
  // one sort last, which is where a newly created workspace belongs.
  order: Zod.number().nullish().catch(undefined),
})

/** Return `widget` in its current shape, upgrading the legacy `button` kind and its inline
action fields to a `controls` widget. */
export function upgradedWidget(widget: Widget): Widget {
  const pages = pagesOf(widget).map((page) => ({
    ...page,
    layout: upgradedRows(page.layout),
  }))

  // A carousel or a tab strip always holds at least one page since one with no pages has no
  // layout to drag or paste widgets into.
  const upgraded = withPages(
    widget,
    pages.length === 0 && (widget.type === 'carousel' || widget.type === 'tabs')
      ? [{ id: v7(), name: '', layout: [] }]
      : pages
  )

  const stored = upgraded as Widget | StoredButtonWidget
  if (stored.type !== 'button') {
    return upgraded
  }

  const { label, address, action, color, styling, tooltip, arguments: values, ...rest } = stored
  const held = { label, address, action, color, styling, tooltip }

  // Stored button widgets carry empty arguments either way so the settable fields decide
  // whether there is a configured button to carry over.
  const wasConfigured = Object.values(held).some((value) => value != null)
  if (stored.buttons.length > 0 || !wasConfigured) {
    return { ...rest, type: 'controls', buttons: stored.buttons }
  }

  return {
    ...rest,
    type: 'controls',
    buttons: [ButtonActionModel.parse({ ...held, arguments: values ?? {} })],
  }
}

export function upgradedRows(rows: WidgetRow[]): WidgetRow[] {
  return rows.map((row) => ({ ...row, widgets: row.widgets.map(upgradedWidget) }))
}

export type WorkspaceDataInput = Zod.input<typeof WorkspaceDataModel>
export type WorkspaceData = Zod.infer<typeof WorkspaceDataModel>
export const WorkspaceDataModel = Zod.object({
  layout: WidgetRowModel.array()
    .catch(() => [])
    .transform(upgradedRows),
  meta: WorkspaceMetaModel.catch(() => ({ order: undefined })),
})

/** Whether a caller may rename, delete, or otherwise write this workspace.

A private workspace belongs to its owner alone so they may write it whatever their access on the
placement. A shared one follows the placement.
*/
export function isWorkspaceWritable(
  workspace: Workspace,
  userId: string | null | undefined,
  canManagePlacement: boolean
): boolean {
  if (workspace.owner_id != null) {
    return workspace.owner_id === userId
  }

  return canManagePlacement
}

/** Sort workspaces into the shared standard order.

Position is carried in each workspace's own data, and those without one sort last, which is where a
newly created workspace belongs. Ties fall back to the name so the order is stable.
*/
export function inStandardOrder(workspaces: Workspace[]): Workspace[] {
  return orderBy(workspaces, [
    (workspace) => workspace.data.meta.order ?? Number.MAX_SAFE_INTEGER,
    (workspace) => workspace.name,
  ])
}

/** Return a workspace's data without `meta`.

`meta` is rewritten by any manager reordering a strip so including it in edit comparisons would
mark every workspace in the strip as edited.
*/
export function withoutMeta(data: WorkspaceData): Omit<WorkspaceData, 'meta'> {
  // Content is named rather than spread so adding a field to a workspace's data fails to compile
  // here until it is decided whether that field is content or presentation.
  const { layout } = data
  return { layout }
}

/** Strip every chart series `id` from `rows`, recursing into carousel and tab pages.

`ChartWidgetSeriesModel.id` mints a fresh ID on every parse of a series stored without one, so an
ID-less legacy series never compares equal to itself across parses. Comparisons that only care
about content go through this first.
*/
function withoutChartSeriesIds(rows: WidgetRow[]): WidgetRow[] {
  return rows.map((row) => ({
    ...row,
    widgets: row.widgets.map((widget) => {
      const pages = pagesOf(widget)
      const scrubbed =
        pages.length === 0
          ? widget
          : withPages(
              widget,
              pages.map((page) => ({ ...page, layout: withoutChartSeriesIds(page.layout) }))
            )

      if (scrubbed.type !== 'chart') {
        return scrubbed
      }

      return {
        ...scrubbed,
        particles: scrubbed.particles.map((particle) => ({
          ...particle,
          series: particle.series.map((series) => omit(series, 'id')),
        })),
      }
    }),
  }))
}

/** Workspace data comparable across parses, with presentation `meta` and minted chart series IDs
removed.

Use for any comparison that should treat two parses of the same content as equal: the `edited`
check, edit reconciliation, and the tab strip's unsaved-edit indicator.
*/
export function comparableWorkspaceData(data: WorkspaceData): Omit<WorkspaceData, 'meta'> {
  return { layout: withoutChartSeriesIds(withoutMeta(data).layout) }
}

export type Workspace = Zod.infer<typeof WorkspaceModel>
export type WorkspaceInput = Zod.input<typeof WorkspaceModel>
export const WorkspaceModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  name: Zod.string(),
  scope: AddressModel.catch(() => Address.parse(engineRoot)),
  owner_id: Zod.string().nullish().catch(null),
  show_when_logged_out: Zod.boolean().catch(false),
  data: WorkspaceDataModel.catch(() => WorkspaceDataModel.parse({})),
})

export type WorkspaceEdit = Zod.infer<typeof WorkspaceEditModel>
export const WorkspaceEditModel = Zod.object({
  user_id: Zod.string(),
  workspace_id: Zod.string(),
  data: WorkspaceDataModel,
})

export type WorkspaceContext = ReturnType<typeof createWorkspaceContext>

/** Handlers a `Workspace.vue` instance exposes to its hosting page, which renders the tab
strip the workspace is shown on. */
export type WorkspaceHeaderActions = {
  rename: (name: string) => void
  openSettings: () => void
  undo: () => void
  redo: () => void
  duplicate: () => void
  exportFile: () => void
  promptDelete: () => void
  promptCommit: () => void
  promptRevert: () => void
  startViewingOriginal: () => void
  stopViewingOriginal: () => void
}

/** State a `Workspace.vue` instance exposes alongside `WorkspaceHeaderActions`, read-only. */
export type WorkspaceHeaderState = {
  edited: boolean
  canManage: boolean
  canEdit: boolean
  canUndo: boolean
  canRedo: boolean
  isViewingOriginal: boolean
}

export type Drag = {
  /** The widget the press landed on. */
  widget: Widget

  /** Everything in hand, in layout order, `widget` among it. */
  widgets: Widget[]

  /** The layout everything came from. A selection is always made within one layout. */
  layout: string
}

/** How a widget joins what is already picked out when it is chosen. */
export type SelectMode = 'replace' | 'toggle' | 'extend'

function createWorkspaceContext(workspaceId: MaybeRef<string>) {
  const auth = useAuth()
  const access = useAccess()
  const workspaces = useWorkspaces()
  const id = $computed(() => unref(workspaceId))

  const query = useQuery({
    queryKey: computed(() => ['workspace-context', id, auth.user?.id]),
    experimental_prefetchInRender: true,
    queryFn: async () => {
      return { workspace: await workspaces.get(id) }
    },
  })

  const workspace = $computed(
    () =>
      (query.data.value?.workspace
        ? readonly(query.data.value.workspace)
        : null) as Workspace | null
  )

  const scope = $computed(() => workspace?.scope ?? null)

  /** Whether the caller may edit and manage this workspace, which are the same right. */
  function isWritable(): boolean {
    if (workspace == null) {
      return false
    }
    if (workspace.owner_id != null) {
      return workspace.owner_id === auth.user?.id
    }

    return access.canManage(workspace.scope.toString())
  }

  function resolveAddress(
    value: string | AddressSelector | null | undefined
  ): AddressSelector | null {
    if (value == null) {
      return null
    }

    return AddressSelector.parse(value).asAbsolute(scope)
  }

  // Whether this workspace is bound to a component rather than the engine root. The root
  // contains every component so a workspace placed there restricts nothing.
  const isBound = $computed(() => scope != null && !scope.isEngine)

  /** Whether an address falls within this workspace's placement.
   *
   * A workspace at the engine root admits every component, one bound to a component admits that
   * component and its descendants. Must agree with what `resolveFilterAddress` produces.
   */
  function isWithinScope(address: Address | string): boolean {
    if (scope == null || scope.isEngine) {
      return true
    }

    const base = scope.toString()
    const value = address.toString()
    return value === base || value.startsWith(`${base}.`)
  }

  // Like `resolveAddress`, but an unset value falls back to the scope's own subtree. A record
  // widget with no address chosen must default to the scope, not to every component.
  function resolveFilterAddress(
    value: string | AddressSelector | null | undefined
  ): AddressSelector | null {
    if (value == null) {
      return scope == null ? null : AddressSelector.parse(`${scope}:all`)
    }

    return AddressSelector.parse(value).asAbsolute(scope)
  }

  let data = $ref<WorkspaceData | null>(null)

  // Undo history for the working copy, capped so a long editing session cannot grow without
  // bound. Snapshots are recorded on the same debounce as the autosave, which groups a burst of
  // drags or keystrokes into one undo step rather than one per frame.
  const historyLimit = 50
  let history = $ref<WorkspaceData[]>([])
  let historyIndex = $ref(-1)

  const canUndo = $computed(() => historyIndex > 0)
  const canRedo = $computed(() => historyIndex >= 0 && historyIndex < history.length - 1)

  function recordHistory() {
    if (data == null) {
      return
    }

    // An undo or redo assigns a state already in the history, which must not be recorded again
    // or it would erase the redo tail it just moved through.
    if (historyIndex >= 0 && isStructurallyEqual(data, history[historyIndex])) {
      return
    }

    const snapshot = deepClone(data) as WorkspaceData
    const kept = [
      ...history.slice(Math.max(0, history.length - historyLimit + 1), historyIndex + 1),
      snapshot,
    ]
    history = kept
    historyIndex = kept.length - 1
  }

  function undo() {
    if (!canUndo) {
      return
    }

    historyIndex--
    data = deepClone(history[historyIndex]) as WorkspaceData
  }

  function redo() {
    if (!canRedo) {
      return
    }

    historyIndex++
    data = deepClone(history[historyIndex]) as WorkspaceData
  }

  async function saveEdit() {
    if (workspace == null || data == null) {
      return
    }

    console.log(`Saving edit for workspace ${id}.`)
    await workspaces.assignEdit(id, data)
  }

  watch(
    () => data,
    debounce(() => {
      recordHistory()
      void saveEdit()
    }, 500),
    { deep: true }
  )

  useEventListener(window, 'beforeunload', async () => {
    try {
      await saveEdit()
    } catch {
      // Ignore.
    }
  })

  // The save watcher is debounced, so an edit made just before the hosting page unmounts, such
  // as the workspace content being hidden, would otherwise never reach the server.
  onScopeDispose(() => {
    void saveEdit()
  })

  const edited = $computed(() => {
    if (data == null || workspace == null) {
      return false
    }

    return !isStructurallyEqual(
      comparableWorkspaceData(data),
      comparableWorkspaceData(workspace.data)
    )
  })

  async function rename(newName: string) {
    return await workspaces.rename(id, newName)
  }

  async function save() {
    if (workspace == null || data == null) {
      return
    }

    console.log(`Saving workspace changes to ${id}.`)
    const result = await update({ data })
    await refresh()
    return result
  }

  async function revert() {
    if (workspace == null || data == null) {
      return
    }

    await refresh()
    if (workspace == null || data == null) {
      return
    }

    console.log(`Discarding workspace changes to ${id}.`)
    data = deepClone(workspace.data) as WorkspaceData
    await workspaces.assignEdit(id, data)
    return workspace
  }

  async function update(data: Partial<Workspace>) {
    return await workspaces.update(id, data)
  }

  async function del() {
    return await workspaces.delete(id)
  }

  async function exportFile() {
    if (workspace == null || data == null) {
      return
    }

    await workspaces.exportFile({
      name: workspace.name,
      data,
    })
  }

  /** Every layout this workspace holds, its own and each carousel slide's, in that order. */
  function layoutRefs(): WorkspaceLayoutRef[] {
    if (data == null) {
      return []
    }

    const current = data
    return collectLayouts(current.layout, (rows) => (current.layout = rows))
  }

  function layoutMap(): Map<string, WidgetRow[]> {
    return new Map(layoutRefs().map((layout) => [layout.id, layout.rows]))
  }

  function findLayout(id: string): WorkspaceLayoutRef | null {
    return layoutRefs().find((layout) => layout.id === id) ?? null
  }

  /** A row opened to hold `widget`, no taller than the widget requires.

  Opening at the default row height would leave a short widget above a band of empty space.
  */
  function openedRow(widgets: Widget[], opening: Widget): WidgetRow {
    return WidgetRowModel.parse({
      widgets,
      height: getWidgetInfo(opening.type).options.minHeight,
    })
  }

  function insertWidget(
    widget: Widget,
    row: number,
    column: number = 0,
    layoutId: string = rootLayoutId
  ) {
    const layout = findLayout(layoutId)
    if (layout == null) {
      return
    }

    const rows = layout.rows
    row = Math.min(rows.length, row)
    const widgets = [...(rows[row]?.widgets ?? [])]
    widgets.splice(column, 0, widget)
    widget.width = Math.min(widgetWidthSubdivisions / widgets.length, widget.width)
    resolveWidgetWidths(widgets, widgets.indexOf(widget))

    if (row < 0) {
      layout.set([openedRow(widgets, widget), ...rows])
    } else if (rows[row] == null) {
      layout.set([...rows, openedRow(widgets, widget)])
    } else {
      const rowObject = rows[row]
      const minHeight = getWidgetInfo(widget.type).options.minHeight
      if (rowObject.height < minHeight) {
        rowObject.height = minHeight
      }

      rowObject.widgets = widgets
    }
  }

  function addWidget(
    type: WidgetType,
    row: number,
    column: number = 0,
    layoutId: string = rootLayoutId
  ) {
    if (data == null) {
      return null
    }

    const widget = createWidget(type)
    insertWidget(widget, row, column, layoutId)

    return widget
  }

  function deleteWidgets(ids: string[]) {
    if (data == null || ids.length === 0) {
      return
    }

    const removed = new Set(ids)

    // Every layout is searched since widgets are deleted by ID and carousel slides hold
    // widgets too.
    for (const layout of layoutRefs()) {
      const rows: WidgetRow[] = []
      let changed = false

      for (const row of layout.rows) {
        const remaining = row.widgets.filter((widget) => !removed.has(widget.id))
        if (remaining.length === row.widgets.length) {
          rows.push(row)
          continue
        }

        changed = true
        if (remaining.length === 0) {
          continue
        }

        resolveWidgetWidths(remaining)
        rows.push({ ...row, widgets: remaining })
      }

      if (changed) {
        layout.set(rows)
      }
    }
  }

  function deleteWidget(id: string) {
    deleteWidgets([id])
  }

  function getWidget(id: string) {
    for (const layout of layoutRefs()) {
      const found = layout.rows.flatMap((row) => row.widgets).find((widget) => widget.id === id)
      if (found != null) {
        return found
      }
    }

    return null
  }

  /** Put `replacement` where the widget named `id` stands, keeping its ID and width. */
  function replaceWidget(id: string, replacement: Widget) {
    for (const layout of layoutRefs()) {
      const existing = layout.rows.flatMap((row) => row.widgets).find((widget) => widget.id === id)
      if (existing == null) {
        continue
      }

      const kept: Widget = { ...replacement, id: existing.id, width: existing.width }
      layout.set(
        layout.rows.map((row) =>
          row.widgets.some((widget) => widget.id === id)
            ? { ...row, widgets: row.widgets.map((widget) => (widget.id === id ? kept : widget)) }
            : row
        )
      )

      return kept
    }

    return null
  }

  /** Group the widgets named by `ids` under a fresh widget of `type`, standing in their place. */
  function groupWidgets(
    ids: string[],
    type: 'tabs' | 'carousel',
    split: GroupSplit = 'widget',
    frameless: boolean = false
  ) {
    if (data == null || ids.length === 0) {
      return null
    }

    // A selection never spans layouts so the first layout that produces a plan held the widgets.
    for (const layout of layoutRefs()) {
      const plan = planWidgetsGroup(layout.rows, ids, type, split, frameless)
      if (plan == null) {
        continue
      }

      layout.set(plan.rows)

      // The holder stands in for what it took so it becomes the selection.
      selectionLayout = layout.id
      selection = [plan.holder.id]
      selectionAnchor = plan.holder.id

      return plan.holder
    }

    return null
  }

  /** Dissolve the pages widget named `id`, its pages' rows standing in its place. */
  function ungroupWidget(id: string) {
    if (data == null) {
      return
    }

    for (const layout of layoutRefs()) {
      const plan = planWidgetUngroup(layout.rows, id)
      if (plan == null) {
        continue
      }

      layout.set(plan.rows)

      // The released widgets become the selection.
      selectionLayout = layout.id
      selection = plan.released.map((widget) => widget.id)
      selectionAnchor = plan.released[plan.released.length - 1]?.id ?? null

      return
    }
  }

  function moveWidgets(ids: string[], placement: WidgetPlacement) {
    if (data == null) {
      return
    }

    const refs = layoutRefs()
    const layouts = new Map(refs.map((layout) => [layout.id, layout.rows]))
    const plan = planWidgetsMove(layouts, ids, placement)
    if (plan == null) {
      return
    }

    // A drop that lands widgets back where they came from changes nothing so skip the rewrite
    // and the server edit.
    if (planIsCurrent(plan, layouts)) {
      return
    }

    const widgets = widgetsIn(layouts)

    for (const [widgetId, width] of Object.entries(plan.widths)) {
      const widget = widgets.get(widgetId)
      if (widget != null) {
        widget.width = width
      }
    }

    // The selection moves with the widgets so a widget dragged into a slide stays selected.
    if (selection.length > 0 && selection.every((id) => ids.includes(id))) {
      selectionLayout = placement.layout
    }

    for (const [layoutId, rows] of Object.entries(plan.layouts)) {
      const layout = refs.find((candidate) => candidate.id === layoutId) ?? null
      layout?.set(
        rows.map((row) => ({
          id: row.id,
          height: row.height,
          collapsed: row.collapsed,
          widgets: row.widgets
            .map((widgetId) => widgets.get(widgetId))
            .filter((widget) => widget != null),
        }))
      )
    }
  }

  // The selected widgets, held as IDs so a layout rebuilt underneath them keeps the selection.
  let selection = $ref<string[]>([])

  // The layout the selection was made in. A selection belongs to one layout at a time.
  let selectionLayout = $ref<string>(rootLayoutId)

  // The widget a range extends from, whichever one was last chosen on its own.
  let selectionAnchor = $ref<string | null>(null)

  function widgetOrder(layoutId: string = selectionLayout): string[] {
    const rows = layoutMap().get(layoutId) ?? []

    return rows.flatMap((row) => row.widgets.map((widget) => widget.id))
  }

  function isSelected(id: string) {
    return selection.includes(id)
  }

  function clearSelection() {
    selection = []
    selectionAnchor = null
  }

  /** Work in `layoutId` from now on, with nothing selected.

  Pressing an empty layout is how it becomes the paste target since it has no widget to select.
  */
  function focusLayout(layoutId: string) {
    selectionLayout = layoutId
    selection = []
    selectionAnchor = null
  }

  function selectWidget(id: string, mode: SelectMode = 'replace', layoutId: string = rootLayoutId) {
    // Selecting in another layout drops the previous selection so there is nothing to extend
    // from or toggle against.
    if (layoutId !== selectionLayout) {
      selectionLayout = layoutId
      selection = [id]
      selectionAnchor = id
      return
    }

    const order = widgetOrder(layoutId)

    if (mode === 'extend' && selectionAnchor != null) {
      const from = order.indexOf(selectionAnchor)
      const to = order.indexOf(id)
      if (from !== -1 && to !== -1) {
        selection = order.slice(Math.min(from, to), Math.max(from, to) + 1)
        return
      }
    }

    if (mode === 'toggle') {
      selection = isSelected(id)
        ? selection.filter((current) => current !== id)
        : [...selection, id]
      selectionAnchor = id
      return
    }

    selection = [id]
    selectionAnchor = id
  }

  /** The selection as text for the system clipboard, or null when nothing is selected. */
  function copySelection(): string | null {
    const layout = findLayout(selectionLayout)
    if (layout == null || selection.length === 0) {
      return null
    }

    const rows = layout.rows
      .map((row) => ({ ...row, widgets: row.widgets.filter((widget) => isSelected(widget.id)) }))
      .filter((row) => row.widgets.length > 0)

    return JSON.stringify({ ceres: 'widgets', rows } satisfies WidgetClipboard, null, 2)
  }

  /** Put the widgets `text` holds into the layout and select them.

  Returns how many landed, zero when the text is not a widget copy.
  */
  function pasteWidgets(text: string): number {
    // Pastes land in the layout being worked in, even when copied from another workspace.
    const layout = findLayout(selectionLayout) ?? findLayout(rootLayoutId)
    if (layout == null) {
      return 0
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      return 0
    }

    const clipboard = WidgetClipboardModel.safeParse(parsed).data ?? null
    if (clipboard == null) {
      return 0
    }

    const pasted: WidgetRow[] = []
    for (const row of clipboard.rows) {
      // Fresh IDs so pasting twice creates two of everything.
      const widgets = row.widgets.map(withFreshIds)
      if (widgets.length === 0) {
        continue
      }

      resolveWidgetWidths(widgets)
      pasted.push({ id: v7(), height: row.height, collapsed: row.collapsed, widgets })
    }

    if (pasted.length === 0) {
      return 0
    }

    // Landing under the selection puts a paste beside its source rather than at the end of the
    // workspace.
    let after = layout.rows.length
    for (const [index, row] of layout.rows.entries()) {
      if (row.widgets.some((widget) => isSelected(widget.id))) {
        after = index + 1
      }
    }

    const rows = [...layout.rows]
    rows.splice(after, 0, ...pasted)
    layout.set(rows)

    selectionLayout = layout.id
    selection = pasted.flatMap((row) => row.widgets.map((widget) => widget.id))
    selectionAnchor = selection[selection.length - 1] ?? null

    return selection.length
  }

  // The selection follows what the layouts actually hold since deletion or undo can remove
  // selected widgets or the layout they were in.
  watchEffect(() => {
    const present = new Set(widgetOrder(selectionLayout))
    const kept = selection.filter((id) => present.has(id))
    if (kept.length !== selection.length) {
      selection = kept
      if (selectionAnchor != null && !present.has(selectionAnchor)) {
        selectionAnchor = null
      }
    }
  })

  function duplicateWidget(
    id: string,
    toRow: number,
    toColumn: number,
    layoutId: string = rootLayoutId
  ) {
    const widget = getWidget(id)
    if (widget == null) {
      return null
    }

    const copy = withFreshIds(deepClone(widget))
    insertWidget(copy, toRow, toColumn, layoutId)
    return copy
  }

  watchEffect(() => {
    for (const layout of layoutRefs()) {
      if (layout.rows.some((row) => row.widgets.length === 0)) {
        layout.set(layout.rows.filter((row) => row.widgets.length > 0))
      }
    }
  })

  // A stored width can be broken, negative or with a total drifted off the row's span. Broken
  // rows are spread back over the full span so they never draw wider than the workspace.
  watchEffect(() => {
    for (const layout of layoutRefs()) {
      for (const row of layout.rows) {
        const widths = row.widgets.map((widget) => widget.width)
        const total = widths.reduce((sum, current) => sum + current, 0)
        if (
          widths.length > 0 &&
          (total !== widgetWidthSubdivisions || widths.some((width) => width <= 0))
        ) {
          const fixed = filledWidths(widths)
          for (const [index, widget] of row.widgets.entries()) {
            widget.width = fixed[index] ?? widget.width
          }
        }
      }
    }
  })

  async function afterFetch() {
    if (data == null) {
      // A failed fetch falls through to stored data, the same as there being no pending edit.
      let edit: WorkspaceEdit | null = null
      try {
        edit = await workspaces.getEdit(id)
      } catch {
        // Ignore.
      }

      data = edit?.data ?? deepClone(workspace?.data ?? null) ?? null

      // Seed the history with the loaded state so the first edit has something to undo back to.
      if (data != null) {
        history = [deepClone(data) as WorkspaceData]
        historyIndex = 0
      }
    }
  }

  // True while a workspace is being fetched and its working copy seeded so a host can tell an
  // empty context apart from one whose workspace does not exist.
  let loading = $ref(true)

  async function load() {
    await query.promise.value
    await afterFetch()
    loading = false
  }

  async function refresh() {
    await query.refetch()
    await workspaces.refresh()
    await afterFetch()
  }

  // The context follows its workspace ID so a host switching workspaces keeps its chrome
  // mounted. The working copy and history belong to the previous workspace so clear them first.
  watch(
    () => id,
    async () => {
      loading = true
      data = null
      history = []
      historyIndex = -1
      await query.promise.value
      await afterFetch()
      loading = false
    }
  )

  return reactive({
    load,
    refresh,
    loading: computed(() => loading),
    name: computed(() => workspace?.name ?? null),
    scope: computed(() => scope),
    resolveAddress,
    resolveFilterAddress,
    isWithinScope,
    isBound: computed(() => isBound),
    owner: computed(() => workspace?.owner_id ?? null),
    isPrivate: computed(() => workspace?.owner_id != null),
    isEnginePlaced: computed(() => workspace?.scope.isEngine === true),
    originalData: computed(() => workspace?.data ?? null),
    data: computed(() => data),
    edited: computed(() => edited),
    canUndo: computed(() => canUndo),
    canRedo: computed(() => canRedo),
    undo,
    redo,
    delete: del,
    rename,
    update,
    save,
    revert,
    exportFile,
    getWidget,
    layouts: computed(() => layoutRefs()),
    insertWidget,
    addWidget,
    deleteWidget,
    deleteWidgets,
    moveWidgets,
    duplicateWidget,
    replaceWidget,
    groupWidgets,
    ungroupWidget,
    drag: null as Drag | null,
    selection: computed(() => selection),
    selectionLayout: computed(() => selectionLayout),
    selectedWidgets: computed(() => {
      const rows = layoutMap().get(selectionLayout) ?? []

      return rows.flatMap((row) => row.widgets).filter((widget) => isSelected(widget.id))
    }),
    isSelected,
    selectWidget,
    clearSelection,
    focusLayout,
    copySelection,
    pasteWidgets,
    // A workspace's access is its placement's, except a private workspace belongs to its owner
    // alone.
    canView: computed(() => {
      if (workspace == null) {
        return false
      }
      if (workspace.owner_id != null) {
        return workspace.owner_id === auth.user?.id
      }

      return access.canView(workspace.scope.toString())
    }),
    canEdit: computed(() => isWritable()),
    canManage: computed(() => isWritable()),
  })
}

export function provideWorkspace(id: MaybeRef<string>) {
  const context = createWorkspaceContext(id)
  provide(workspaceInjectionKey, context)
  return context
}

export function useWorkspace() {
  const workspace = inject(workspaceInjectionKey)
  if (workspace == null) {
    throw new Error('Workspace context not found.')
  }

  return workspace
}

export const useWorkspaces = defineStore('workspaces', () => {
  const navigation = useNavigation()
  const client = useClient()
  const auth = useAuth()
  const notify = useNotify()

  function getUserId() {
    if (auth.user == null) {
      throw new Error('Not logged in.')
    }

    return auth.user.id
  }

  async function get(id: string) {
    return await client.get(`/api/workspaces/${id}`, {
      parse: WorkspaceModel,
    })
  }

  // Every workspace the caller may see. The server limits to viewable placements plus the
  // private workspaces they own.
  async function getAll() {
    return await client.get(`/api/workspaces`, {
      parse: Zod.array(WorkspaceModel),
    })
  }

  async function listScoped(scope: Address) {
    return await client.get(`/api/workspaces`, {
      parse: Zod.array(WorkspaceModel),
      query: {
        scope: scope.toString(),
      },
    })
  }

  const query = useQuery({
    queryKey: computed(() => ['workspaces', auth.user?.id]),
    queryFn: async () => {
      return { all: await getAll() }
    },
    enabled: computed(() => auth.user != null),
  })

  async function load() {
    await query.promise.value
  }

  async function refresh() {
    await query.refetch()
  }

  const allWorkspaces = $computed(
    () => new Map((query.data.value?.all ?? []).map((workspace) => [workspace.id, workspace]))
  )

  async function create(
    workspace?: Omit<WorkspaceInput, 'name'> & { name?: string }
  ): Promise<Workspace> {
    workspace = WorkspaceModel.parse({ name: 'Workspace', ...workspace })
    const result = await client.post(`/api/workspaces`, {
      data: workspace,
      parse: WorkspaceModel,
    })
    await refresh()
    return result
  }

  async function update(id: string, data: Partial<Workspace>) {
    const result = await client.patch(`/api/workspaces/${id}`, {
      data: WorkspaceModel.partial().parse(data),
      parse: WorkspaceModel,
    })
    await refresh()
    return result
  }

  async function rename(id: string, name: string) {
    return await update(id, { name })
  }

  /** Show a workspace on home by naming it in the query.

  Home reads the query and adds the workspace to its strip so a link, a sidebar click, and an
  action all arrive the same way. The workspace keeps its placement.
  */
  async function open(id: string) {
    await navigation.push({ path: '/', query: { [workspaceQueryKey]: id } })
  }

  /** Copy a link that opens workspaces on the page a placement belongs to.

  The query is read on arrival and removed from the bar so a shareable link exists only through
  this.
  */
  async function copyLink(placement: string, ids: string[]) {
    const path = placement === engineRoot ? '/' : `/components/${placement}`
    const { href } = navigation.resolve({ path, query: { [workspaceQueryKey]: ids } })

    await copyToClipboard(window.location.origin + href)
    notify.success(ids.length > 1 ? 'Links copied to clipboard.' : 'Link copied to clipboard.')
  }

  async function del(id: string) {
    const result = await client.delete(`/api/workspaces/${id}`, {
      parse: WorkspaceModel,
    })
    await refresh()
    return result
  }

  /** This user's pending edit for `workspaceId`, null when none exists.

  Rethrows on any failure other than not-found, so a caller reconciling the edit against fresh
  data can tell "no edit" apart from "could not check."
  */
  async function getEdit(workspaceId: string) {
    if (auth.user == null) {
      return null
    }

    try {
      return await client.get(`/api/users/${auth.user.id}/workspace-edits/${workspaceId}`, {
        parse: WorkspaceEditModel,
      })
    } catch (error) {
      if (error instanceof Failure && error.error.type === 'not-found-error') {
        return null
      }

      throw error
    }
  }

  async function assignEdit(workspaceId: string, data: WorkspaceData) {
    return await client.put(`/api/users/${getUserId()}/workspace-edits/${workspaceId}`, {
      data: {
        // `meta` is shared so an edit carries content only. Committing an edit must not restore
        // the tab order that was in force when the edit began.
        data: withoutMeta(data),
      },
      parse: WorkspaceEditModel,
    })
  }

  // Lets the component-scoped tab strip learn which workspaces still have unsaved edits
  // without loading each one's full context.
  async function getEdits(workspaceIds: string[]) {
    if (auth.user == null || workspaceIds.length === 0) {
      return []
    }

    return await client.get(`/api/users/${auth.user.id}/workspace-edits`, {
      parse: Zod.array(WorkspaceEditModel),
      query: {
        'workspace-id': workspaceIds,
      },
    })
  }

  async function discardEdit(workspaceId: string) {
    if (auth.user == null) {
      return null
    }

    try {
      await client.delete(`/api/users/${auth.user.id}/workspace-edits/${workspaceId}`, {
        parse: WorkspaceEditModel,
      })
    } catch {
      return null
    }
  }

  async function exportFile(workspaceOrId: string | WorkspaceInput) {
    const workspace = typeof workspaceOrId === 'string' ? await get(workspaceOrId) : workspaceOrId
    if (workspace == null) {
      notify.error('Workspace not found.')
      return
    }

    const json = JSON.stringify(
      {
        name: workspace.name,
        data: workspace.data,
      },
      null,
      2
    )

    download(`${workspace.name}.workspace.json`, json)
  }

  /** Import exported workspace files, placing each one on `placement`. */
  async function importWorkspaces(
    files: Iterable<File>,
    placement?: { scope?: Address; owner_id?: string | null }
  ) {
    const imported: Workspace[] = []

    for (const file of files) {
      let parsed: unknown
      try {
        parsed = JSON.parse(await file.text())
      } catch {
        notify.error(`Import of '${file.name}' failed. Invalid JSON.`)
        continue
      }

      const { data: workspace, error } = WorkspaceModel.safeParse(parsed)
      if (error != null) {
        notify.error(`Import of '${file.name}' failed. Invalid workspace file. ${error.message}`)
        continue
      }

      // Only the name and contents travel so the import lands where the user dropped it.
      const created = await create({
        name: workspace.name,
        data: workspace.data,
        ...placement,
      })
      imported.push(created)
    }

    if (imported.length > 0) {
      notify.success(`${imported.length} workspace(s) imported successfully.`)
    }

    return imported
  }

  async function importFiles(placement?: { scope?: Address; owner_id?: string | null }) {
    const files = await selectFile({ multiple: true, accept: 'application/json' })
    if (files == null) {
      return null
    }

    return await importWorkspaces(files, placement)
  }

  return {
    load,
    refresh,
    all: computed(() => [...allWorkspaces.values()]),
    get,
    getAll,
    listScoped,
    create,
    rename,
    update,
    open,
    copyLink,
    delete: del,
    getEdit,
    getEdits,
    assignEdit,
    discardEdit,
    importFiles,
    importWorkspaces,
    exportFile,
  }
})

export const widgetWidthSubdivisions = 120
export const minWidgetWidthPixels = 100

// The narrowest a width may be squeezed to. A zero or negative width stores a widget nothing can
// grab and draws its neighbours past the row's edge.
const minWidthUnits = 1

/** Spread a row's widths back over `widgetWidthSubdivisions`, without touching any widget.

`keepIndices` names widths to leave alone, absorbing the difference into every other width or,
with `adjustMode` set to `after`, only into the ones that follow. No width goes below
`minWidthUnits`, and the result totals `widgetWidthSubdivisions` while any width can still give.
*/
export function resolveWidths(
  widths: number[],
  keepIndices?: number | number[],
  adjustMode: 'after' | 'other' = 'other'
): number[] {
  if (widths.length === 0) {
    return []
  }

  const kept = (
    keepIndices == null ? [] : Array.isArray(keepIndices) ? keepIndices : [keepIndices]
  ).filter((index) => index >= 0)

  const totalWidthUnits = widths.reduce((sum, current) => sum + current, 0)
  if (
    totalWidthUnits === widgetWidthSubdivisions &&
    widths.every((width) => width >= minWidthUnits)
  ) {
    return [...widths]
  }

  const indices = widths.map((_, index) => index)

  let adjusted: number[]
  if (kept.length === 0) {
    adjusted = indices
  } else {
    if (adjustMode === 'after') {
      adjusted = indices.slice(Math.max(...kept) + 1)
    } else {
      adjusted = indices.filter((index) => !kept.includes(index))
    }
  }

  if (adjusted.length === 0) {
    adjusted = indices
  }

  const resolved = [...widths]

  // A width already below the floor gives nothing so it is lifted first and the lift joins the
  // excess the others have to absorb.
  for (const index of indices) {
    const width = resolved[index] ?? 0
    if (width < minWidthUnits) {
      resolved[index] = minWidthUnits
    }
  }

  // Spread the excess over the adjustable widths, evenly, in passes. A width that would be taken
  // below the floor stops there, and what it could not give is spread over the rest on the next
  // pass so one pass per width bounds the loop.
  for (let pass = 0; pass <= widths.length; pass++) {
    const excess = resolved.reduce((sum, current) => sum + current, 0) - widgetWidthSubdivisions
    if (excess === 0) {
      break
    }

    const givers =
      excess > 0 ? adjusted.filter((index) => (resolved[index] ?? 0) > minWidthUnits) : adjusted
    if (givers.length === 0) {
      break
    }

    const share = excess / givers.length
    for (const index of givers) {
      const width = resolved[index] ?? 0
      resolved[index] = excess > 0 ? Math.max(width - share, minWidthUnits) : width - share
    }
  }

  // Round to whole units without moving the total, pushing the drift one unit at a time onto the
  // adjustable widths, into the widest when taking so nothing crosses the floor.
  const rounded = resolved.map((width) => Math.round(width))
  let drift =
    Math.round(resolved.reduce((sum, current) => sum + current, 0)) -
    rounded.reduce((sum, current) => sum + current, 0)
  while (drift !== 0) {
    const step = Math.sign(drift)
    const candidates =
      step > 0 ? adjusted : adjusted.filter((index) => (rounded[index] ?? 0) > minWidthUnits)
    if (candidates.length === 0) {
      break
    }

    const target = candidates.reduce((best, index) =>
      step < 0
        ? (rounded[index] ?? 0) > (rounded[best] ?? 0)
          ? index
          : best
        : (rounded[index] ?? 0) < (rounded[best] ?? 0)
        ? index
        : best
    )
    rounded[target] = (rounded[target] ?? 0) + step
    drift -= step
  }

  return rounded
}

export function resolveWidgetWidths(
  widgets: Widget[],
  keepIndices?: number | number[],
  adjustMode: 'after' | 'other' = 'other'
) {
  const resolved = resolveWidths(
    widgets.map((widget) => widget.width),
    keepIndices,
    adjustMode
  )

  for (const [index, widget] of widgets.entries()) {
    if (widget.width !== resolved[index]) {
      widget.width = resolved[index]
    }
  }
}

/** The pages a widget holds, or none.

Everything that walks a workspace's layouts goes through here so a new pages-holding widget kind
only needs to be named here.
*/
export function pagesOf(widget: Widget): WidgetPage[] {
  if (widget.type === 'carousel') {
    return widget.slides
  }
  if (widget.type === 'tabs') {
    return widget.tabs
  }

  return []
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

/** A copy of `widget` holding `pages` in place of the ones it held. */
export function withPages(widget: Widget, pages: WidgetPage[]): Widget {
  if (widget.type === 'carousel') {
    return { ...widget, slides: pages }
  }
  if (widget.type === 'tabs') {
    return { ...widget, tabs: pages }
  }

  return widget
}

/** How grouping deals the taken widgets across the pages of the new widget. */
export type GroupSplit = 'widget' | 'row' | 'none'

/** Scale `widths` to fill a row, keeping their proportions.

A width at or below zero poisons the proportions so a row holding one is dealt out evenly
instead.
*/
function filledWidths(widths: number[]): number[] {
  if (widths.length === 0) {
    return []
  }

  const usable = widths.every((width) => width > 0)
  const basis = usable ? widths : widths.map(() => 1)
  const basisTotal = usable ? widths.reduce((sum, current) => sum + current, 0) : widths.length
  const scaled = basis.map((width) => Math.round((width * widgetWidthSubdivisions) / basisTotal))

  // Rounding drift lands on the last width so the row still adds up exactly.
  const drift = widgetWidthSubdivisions - scaled.reduce((sum, current) => sum + current, 0)
  scaled[scaled.length - 1] = (scaled[scaled.length - 1] ?? 0) + drift

  return scaled
}

/** Group the widgets named by `ids` under a fresh widget of `type`, standing where the first
stood.

The taken widgets land on the holder's pages as `split` says, a page per widget, a page per
source row, or all on one page. Page rows keep their heights, the holder takes the taken widgets'
room in its own row, and emptied rows close up. With `frameless` set the taken widgets land
without their frames. Returns null when none of the named widgets stand in `rows`.
*/
export function planWidgetsGroup(
  rows: WidgetRow[],
  ids: string[],
  type: 'tabs' | 'carousel',
  split: GroupSplit,
  frameless: boolean = false
): { rows: WidgetRow[]; holder: Widget } | null {
  const taking = new Set(ids)

  type Group = { row: WidgetRow; taken: Widget[]; staying: Widget[] }
  const groups = new Map<WidgetRow, Group>()
  for (const row of rows) {
    const taken = row.widgets.filter((widget) => taking.has(widget.id))
    if (taken.length > 0) {
      groups.set(row, {
        row,
        taken,
        staying: row.widgets.filter((widget) => !taking.has(widget.id)),
      })
    }
  }

  if (groups.size === 0) {
    return null
  }

  const groupList = [...groups.values()]

  function pageRow(source: WidgetRow, taken: Widget[]): WidgetRow {
    const widths = filledWidths(taken.map((widget) => widget.width))
    return {
      id: v7(),
      height: source.height,
      collapsed: source.collapsed,
      widgets: taken.map((widget, index) => ({
        ...widget,
        width: widths[index] ?? widget.width,
        frameless: frameless || widget.frameless,
      })),
    }
  }

  let pages: WidgetPage[]
  if (split === 'widget') {
    // Each page is named after its widget since the strip then stands for the widgets on it.
    pages = groupList.flatMap(({ row, taken }) =>
      taken.map((widget) => ({ id: v7(), name: widget.name, layout: [pageRow(row, [widget])] }))
    )
  } else if (split === 'row') {
    pages = groupList.map(({ row, taken }) => ({
      id: v7(),
      name: '',
      layout: [pageRow(row, taken)],
    }))
  } else {
    pages = [{ id: v7(), name: '', layout: groupList.map(({ row, taken }) => pageRow(row, taken)) }]
  }

  const base = createWidget(type)
  const first = groupList[0] as Group
  const width = Math.min(
    first.taken.reduce((sum, widget) => sum + widget.width, 0),
    widgetWidthSubdivisions
  )
  const holder: Widget = { ...withPages(base, pages), width }

  const result: WidgetRow[] = []
  for (const row of rows) {
    const group = groups.get(row)
    if (group == null) {
      result.push(row)
    } else if (group === first) {
      // Everything before the first taken widget is staying so its index in the old row is also
      // the holder's place among what stays.
      const at = row.widgets.findIndex((widget) => taking.has(widget.id))
      const widgets = [...group.staying]
      widgets.splice(at, 0, holder)
      result.push({ ...row, widgets })
    } else if (group.staying.length > 0) {
      const widths = resolveWidths(group.staying.map((widget) => widget.width))
      result.push({
        ...row,
        widgets: group.staying.map((widget, index) => ({
          ...widget,
          width: widths[index] ?? widget.width,
        })),
      })
    }
  }

  return { rows: result, holder }
}

/** Dissolve the pages widget named `id` back into `rows`, its pages' rows standing in its place.

A row the widget shared stays ahead of them, holding the widgets that remain on it. Returns null
when no widget named `id` stands in `rows`, or when the named one holds no pages.
*/
export function planWidgetUngroup(
  rows: WidgetRow[],
  id: string
): { rows: WidgetRow[]; released: Widget[] } | null {
  const at = rows.findIndex((row) => row.widgets.some((widget) => widget.id === id))
  if (at < 0) {
    return null
  }

  const row = rows[at] as WidgetRow
  const target = row.widgets.find((widget) => widget.id === id) as Widget
  const pages = pagesOf(target)
  if (pages.length === 0) {
    return null
  }

  const landing = pages.flatMap((page) => page.layout)
  const staying = row.widgets.filter((widget) => widget.id !== id)

  const result = [...rows]
  if (staying.length === 0) {
    result.splice(at, 1, ...landing)
  } else {
    const widths = resolveWidths(staying.map((widget) => widget.width))
    result.splice(
      at,
      1,
      {
        ...row,
        widgets: staying.map((widget, index) => ({
          ...widget,
          width: widths[index] ?? widget.width,
        })),
      },
      ...landing
    )
  }

  return { rows: result, released: landing.flatMap((current) => current.widgets) }
}

/** The ID of the workspace's own layout, as opposed to one belonging to a widget's page. */
export const rootLayoutId = 'root'

/** A layout a workspace holds, by ID.

The workspace has one of its own, and every widget page anywhere inside it holds another, all
arranged the same way.
*/
export type WorkspaceLayoutRef = {
  id: string
  rows: WidgetRow[]

  /** Put a rearranged layout back where this one came from. */
  set: (rows: WidgetRow[]) => void
}

/** Collect every layout reachable from `root`, the workspace's own first. */
export function collectLayouts(
  root: WidgetRow[],
  setRoot: (rows: WidgetRow[]) => void
): WorkspaceLayoutRef[] {
  const found: WorkspaceLayoutRef[] = [{ id: rootLayoutId, rows: root, set: setRoot }]

  function visit(rows: WidgetRow[]) {
    for (const row of rows) {
      for (const widget of row.widgets) {
        for (const page of pagesOf(widget)) {
          found.push({
            id: page.id,
            rows: page.layout,
            set: (replacement) => (page.layout = replacement),
          })
          visit(page.layout)
        }
      }
    }
  }

  visit(root)

  return found
}

/** A copy of `widget` under fresh IDs, all the way down.

A copy keeping any stored ID would leave two things answering to it wherever lookups go by ID.
*/
export function withFreshIds(widget: Widget): Widget {
  const copy: Widget = { ...widget, id: v7() }

  // Buttons carry IDs of their own.
  if (copy.type === 'controls') {
    copy.buttons = copy.buttons.map((button) => ({ ...button, id: v7() }))
  }

  // Chart series carry IDs of their own.
  if (copy.type === 'chart') {
    copy.particles = copy.particles.map((particle) => ({
      ...particle,
      series: particle.series.map((series) => ({ ...series, id: v7() })),
    }))
  }

  return withPages(copy, pagesOf(copy).map(withFreshPage))
}

/** A copy of `page` under fresh IDs, all the way down. */
export function withFreshPage(page: WidgetPage): WidgetPage {
  return {
    ...page,
    id: v7(),
    layout: page.layout.map((row) => ({
      ...row,
      id: v7(),
      widgets: row.widgets.map(withFreshIds),
    })),
  }
}

/** Every layout held inside `widgets`, however deep, which no drop may land inside. */
export function layoutsWithin(widgets: Widget[]): Set<string> {
  const found = new Set<string>()

  function visit(list: Widget[]) {
    for (const widget of list) {
      for (const page of pagesOf(widget)) {
        found.add(page.id)
        visit(page.layout.flatMap((row) => row.widgets))
      }
    }
  }

  visit(widgets)

  return found
}

/** Where a widget in hand would land.

Both indices read against the layout with that widget already taken out of it, which is the layout
its owner is looking at while the drag is in progress.
*/
export type WidgetPlacement = {
  /** Which layout it lands in, the workspace's own or a carousel slide's. */
  layout: string

  /** Row to drop into, or the index the new row takes when `column` is null. */
  row: number

  /** Insertion index within that row, or null to open a row of its own. */
  column: number | null
}

/** A row of a planned layout, in widget IDs, so it can be drawn before it is applied. */
export type PlannedRow = {
  id: string
  height: number
  collapsed: boolean
  widgets: string[]
}

/** The layouts a move settles on so they can be drawn before the move is applied.

A move touches the layout the widgets left and the one they arrive in, which are the same layout
whenever a drag stays where it started. Layouts the move leaves alone are absent.
*/
export type WidgetMovePlan = {
  layouts: Record<string, PlannedRow[]>

  /** The widths the move settles on, by widget ID. Widgets left at their own width are absent. */
  widths: Record<string, number>
}

/** Every widget in `layouts`, by ID. */
function widgetsIn(layouts: Map<string, WidgetRow[]>): Map<string, Widget> {
  return new Map(
    [...layouts.values()]
      .flatMap((rows) => rows.flatMap((row) => row.widgets))
      .map((widget) => [widget.id, widget])
  )
}

/** Whether a plan describes the layouts that are already there, down to the widths. */
function planIsCurrent(plan: WidgetMovePlan, layouts: Map<string, WidgetRow[]>): boolean {
  for (const [layoutId, rows] of Object.entries(plan.layouts)) {
    const current = layouts.get(layoutId) ?? null
    if (current == null || rows.length !== current.length) {
      return false
    }

    for (const [index, row] of rows.entries()) {
      const currentRow = current[index]
      if (
        row.id !== currentRow.id ||
        row.height !== currentRow.height ||
        row.collapsed !== currentRow.collapsed ||
        row.widgets.length !== currentRow.widgets.length
      ) {
        return false
      }

      for (const [position, widgetId] of row.widgets.entries()) {
        if (widgetId !== currentRow.widgets[position].id) {
          return false
        }
      }
    }
  }

  const widgets = widgetsIn(layouts)

  return Object.entries(plan.widths).every(
    ([widgetId, width]) => widgets.get(widgetId)?.width === width
  )
}

/** Work out the layouts that moving `ids` to `placement` produces, changing nothing.

Widgets keep the rows they came from when the drop opens rows of its own, and a drop into an
existing row puts the whole selection there side by side. A null `placement` plans the removal
alone, for display while widgets are in hand. Returns null when no layout holds any of `ids`,
when the placement names a missing row, or when it names a layout a widget in hand carries.
*/
export function planWidgetsMove(
  layouts: Map<string, WidgetRow[]>,
  ids: string[],
  placement: WidgetPlacement | null,

  /** How tall each row actually renders, by row ID, where that differs from its stored height.
  A widget carried out of a stretched or squeezed slide row arrives at the size it was shown at. */
  shown?: Map<string, number>
): WidgetMovePlan | null {
  const held = new Set(ids)

  /** The height a row actually renders at, which a widget leaving it carries away. */
  function heightOf(row: WidgetRow): number {
    return Math.round(shown?.get(row.id) ?? row.height)
  }

  // The layout the widgets came out of. A drag holds widgets from one layout at a time.
  let sourceId: string | null = null
  let source: WidgetRow[] | null = null
  for (const [layoutId, rows] of layouts) {
    if (rows.some((row) => row.widgets.some((widget) => held.has(widget.id)))) {
      sourceId = layoutId
      source = rows
      break
    }
  }
  if (sourceId == null || source == null) {
    return null
  }

  const widths: Record<string, number> = {}

  // What is in hand, grouped by source row in layout order. A group becomes a row again when the
  // drop opens rows rather than joining one.
  const groups: { row: WidgetRow; widgets: Widget[]; consumed: boolean }[] = []

  // Take the widgets out first so the placement's indices read against the layout without them.
  const rows = source.map((row) => {
    const taken = row.widgets.filter((widget) => held.has(widget.id))
    const remaining = row.widgets.filter((widget) => !held.has(widget.id))

    if (taken.length > 0) {
      groups.push({ row, widgets: taken, consumed: remaining.length === 0 })

      const resolved = resolveWidths(remaining.map((widget) => widget.width))
      for (const [index, widget] of remaining.entries()) {
        widths[widget.id] = resolved[index]
      }
    }

    return {
      id: row.id,
      height: row.height,
      collapsed: row.collapsed,
      widgets: remaining.map((widget) => widget.id),
    }
  })

  if (groups.length === 0) {
    return null
  }

  const kept = rows.filter((row) => row.widgets.length > 0)
  if (placement == null) {
    return { layouts: { [sourceId]: kept }, widths }
  }

  const carried = groups.flatMap((group) => group.widgets)

  // A carousel cannot be dropped onto a slide of its own, the layout would then hold the widget
  // holding it.
  if (layoutsWithin(carried).has(placement.layout)) {
    return null
  }

  // Arriving back in the source layout drops into the rows the widgets were just taken out of.
  const intoSource = placement.layout === sourceId
  const target = intoSource
    ? kept
    : layouts.get(placement.layout)?.map((row) => ({
        id: row.id,
        height: row.height,
        collapsed: row.collapsed,
        widgets: row.widgets.map((widget) => widget.id),
      })) ?? null
  if (target == null) {
    return null
  }

  const planned = () =>
    intoSource ? { [sourceId]: kept } : { [sourceId]: kept, [placement.layout]: target }

  if (placement.column == null) {
    const opened = groups.map((group) => {
      const resolved = resolveWidths(group.widgets.map((widget) => widget.width))
      for (const [index, widget] of group.widgets.entries()) {
        widths[widget.id] = resolved[index]
      }

      return {
        // An emptied row's ID passes to the row taking its place so a selection dropped back
        // where it started reads as no change.
        id: group.consumed ? group.row.id : v7(),
        height: heightOf(group.row),
        collapsed: group.row.collapsed,
        widgets: group.widgets.map((widget) => widget.id),
      }
    })

    target.splice(placement.row, 0, ...opened)
    return { layouts: planned(), widths }
  }

  const destinationRow = target[placement.row] ?? null
  if (destinationRow == null) {
    return null
  }

  destinationRow.widgets.splice(placement.column, 0, ...carried.map((widget) => widget.id))
  destinationRow.height = Math.max(
    destinationRow.height,
    ...groups.map((group) => heightOf(group.row))
  )

  // Each arriving widget claims at most an even share of the row it joins, and the widgets
  // already there give up the difference. Widths are read across every layout since an arriving
  // widget's width comes from the one it left.
  const currentWidths = widgetsIn(layouts)
  const share = widgetWidthSubdivisions / destinationRow.widgets.length
  const resolved = resolveWidths(
    destinationRow.widgets.map((widgetId) => {
      const width = currentWidths.get(widgetId)?.width ?? 0

      return held.has(widgetId) ? Math.min(share, width) : width
    }),
    carried.map((_, offset) => (placement.column ?? 0) + offset)
  )
  for (const [index, widgetId] of destinationRow.widgets.entries()) {
    widths[widgetId] = resolved[index]
  }

  return { layouts: planned(), widths }
}

/** The one component a widget is pointed at, or null when it is pointed at none.

A widget pointed at several components returns none since the header's shortcut is for a view of
one thing.
*/
export function widgetTargetSelector(widget: Widget): Address | AddressSelector | null {
  if (widget.restricted) {
    return null
  }

  switch (widget.type) {
    case 'procedures':
      return widget.procedureAddress ?? null
    case 'value':
      return widget.particleAddress ?? null
    default:
      return null
  }
}

// A value that changes whenever any of a widget's address-bearing fields change. Used to clear a
// restricted stub's lock placeholder when the user repoints it.
export function widgetTargetSignature(widget: Widget): string {
  const values: unknown[] = []

  if ('address' in widget) {
    values.push(widget.address)
  }
  if ('commandAddress' in widget) {
    values.push(widget.commandAddress)
  }
  if ('procedureAddress' in widget) {
    values.push(widget.procedureAddress)
  }
  if ('particleAddress' in widget) {
    values.push(widget.particleAddress)
  }
  if ('query' in widget) {
    values.push(widget.query)
  }
  if ('filter' in widget) {
    // Guarded since an unknown kind can carry a `filter` of any shape at all.
    values.push((widget.filter as { address?: unknown } | null)?.address)
  }
  if ('particles' in widget) {
    values.push(widget.particles.map((particle) => particle.address?.toString() ?? null))
  }
  if ('buttons' in widget) {
    values.push(widget.buttons.map((button) => button.address?.toString() ?? null))
  }

  return JSON.stringify(values.map((value) => value?.toString() ?? null))
}
