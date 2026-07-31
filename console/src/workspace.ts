import { useQuery } from '@tanstack/vue-query'
import { useEventListener } from '@vueuse/core'
import { debounce, orderBy } from 'lodash-es'
import { defineStore } from 'pinia'
import { copyToClipboard, exportFile as download } from 'quasar'
import { v7 } from 'uuid'
import {
  computed,
  defineAsyncComponent,
  inject,
  MaybeRef,
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

  // Whether the widget stands on the layout without a card and a header around it. What it shows
  // is then all there is of it, and the handle it is arranged by comes up over it on hover.
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

  // Pressing a button asks for the action's arguments before running it, since an action worth
  // putting on a workspace is usually one that takes some. Locked, the arguments it was left with
  // are the arguments it runs with, and pressing it runs it.
  locked: Zod.boolean().catch(false),

  /** Whether running it asks first, for an action that would be unwelcome by accident. */
  confirm: Zod.boolean().catch(false),
})

/** Actions offered side by side, laid out as a bar rather than one to a widget. */
export type ButtonWidget = BaseWidget & {
  type: 'button'
  buttons: ButtonAction[]
}

/** A button widget as one may still be stored, from when it offered a single action.

The fields it held are named here rather than on `ButtonWidget`, so that the rest of the app can
only reach a button's action through `buttons` and cannot pick up a shape `upgradedWidget` has
already put behind it.
*/
type StoredButtonWidget = ButtonWidget & Partial<Omit<ButtonAction, 'id' | 'locked' | 'confirm'>>

export const ButtonWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('button'),
  name: Zod.string().catch(''),
  buttons: safeArrayOf(ButtonActionModel),

  // A button widget wears no frame of its own by default, being a bar of controls rather than a
  // view of something.
  frameless: Zod.boolean().catch(true),

  // What a button widget held when it offered one action and held its fields itself. Kept so that
  // a stored workspace still parses, and folded into `buttons` by `upgradedWidget` as it loads.
  label: Zod.string().nullish(),
  address: AddressModel.nullish(),
  action: Zod.string().nullish(),
  arguments: Zod.record(Zod.string(), Zod.any()).nullish(),
  color: ColorModel.nullish().catch(undefined),
  styling: ButtonStylingModel.nullish().catch(undefined),
  tooltip: Zod.string().nullish().catch(undefined),
})

/** A layout held under a name of its own, which is what a carousel slide and a tab both are.

Written out rather than inferred, since a page holds rows, a row holds widgets, and a widget may
hold pages of its own. Naming the types breaks a circle the compiler cannot see the end of.
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

export type CarouselWidget = BaseWidget & {
  type: 'carousel'
  slides: WidgetPage[]

  /** How long each slide is shown, in seconds. */
  interval: number

  /** Whether it moves on by itself, as against being stepped through by hand. */
  autoplay: boolean
}

export const CarouselWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('carousel'),
  name: Zod.string().catch('Carousel'),
  slides: safeArrayOf(WidgetPageModel),
  interval: Zod.number().min(1).max(3600).catch(15),
  // Off to begin with. A panel that starts moving on its own the moment it is added takes the
  // page over before anyone has said what is meant to be on it.
  autoplay: Zod.boolean().catch(false),
})

/** Pages shown one at a time, reached by name rather than in turn. */
export type TabsWidget = BaseWidget & {
  type: 'tabs'
  tabs: WidgetPage[]
}

export const TabsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('tabs'),
  name: Zod.string().catch('Tabs'),
  tabs: safeArrayOf(WidgetPageModel),
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
  | ButtonWidget
  | CarouselWidget
  | TabsWidget

export const WidgetModel = Zod.discriminatedUnion('type', [
  MessagesWidgetModel,
  ParticlesWidgetModel,
  AlertsWidgetModel,
  LogsWidgetModel,
  ProceduresWidgetModel,
  ChartWidgetModel,
  ValueWidgetModel,
  VideoWidgetModel,
  ButtonWidgetModel,
  CarouselWidgetModel,
  TabsWidgetModel,
])

export type WidgetType = Widget['type']
export type WidgetInfo = (typeof widgetInfos)[keyof typeof widgetInfos]
export type WidgetComponent = (typeof widgetInfos)[WidgetType]['component']

const defaultMinHeight = 150
const defaultPaddingClass = 'q-pa-sm'

export function getWidgetInfo(type: WidgetType): WidgetInfo {
  return widgetInfos[type]
}

/** The name a widget of `type` carries when nothing has been made of it.

A name nobody chose should not outlive the kind of widget it was the default for, so turning one
kind into another compares against this to tell a chosen name from an inherited one.
*/
export function defaultWidgetName(type: WidgetType): string {
  return createWidget(type).name
}

/** Build a widget of `type`, whose defaults are whatever its own model says they are.

Said as a cast, because a carousel holds slides that hold rows that hold widgets, and the compiler
gives up on a shape that reaches back into itself. The models still describe it exactly.
*/
export function createWidget(type: WidgetType): Widget {
  return widgetInfos[type].model.parse({ type }) as Widget
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
    // No settings of its own, for the same reason a carousel has none. Its pages are arranged on
    // the strip that names them.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  carousel: {
    type: 'carousel',
    name: 'Carousel',
    model: CarouselWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetCarousel.vue')),
    // No settings of its own. A carousel is arranged on the carousel, and how it runs is set from
    // the band of controls under its slides, beside the slides those settings act on.
    options: widgetOptions({
      paddingClass: [],
    }),
  },
  button: {
    type: 'button',
    name: 'Button',
    model: ButtonWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetButton.vue')),
    // No settings of its own. Each button is configured from the button itself, since a widget
    // holding several has nothing left to say about all of them at once.
    options: widgetOptions({
      minHeight: 50,
      fullHeight: false,
    }),
  },
} as const

/** Written out for the same reason `WidgetPage` is, being the other half of the same circle. */
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

/** Widgets on the system clipboard, laid out the way they were taken.

Rows are kept rather than a flat list, so a block copied out of a workspace comes back with the
shape it had, the same as one dragged across it. The marker is what tells a paste of widgets apart
from a paste of any other text.
*/
export type WidgetClipboard = Zod.infer<typeof WidgetClipboardModel>
export const WidgetClipboardModel = Zod.object({
  ceres: Zod.literal('widgets'),
  // Upgraded on the way in, since a copy may have been taken before the workspace it came from
  // was, or taken from a workspace nobody has opened since.
  rows: safeArrayOf(WidgetRowModel).transform(upgradedRows),
})

export type WorkspaceMeta = Zod.infer<typeof WorkspaceMetaModel>

/** Presentation state the console keeps alongside a workspace's contents.

The engine stores this without interpreting it, so nothing here may affect how a workspace
behaves, only how the console chooses to display it.
*/
export const WorkspaceMetaModel = Zod.object({
  // Position among the workspaces scoped to the same component, ascending. Workspaces without
  // one sort last, which is where a newly created workspace belongs.
  order: Zod.number().nullish().catch(undefined),
})

/** A widget as the app understands it now, whatever shape it was stored in.

A button widget once offered one action and held that action's fields itself. It now offers as many
as are put on it, so a stored one becomes a widget holding the single button it always was. The old
fields are left behind rather than carried, so the next write puts the new shape back.
*/
export function upgradedWidget(widget: Widget): Widget {
  const upgraded = withPages(
    widget,
    pagesOf(widget).map((page) => ({
      ...page,
      layout: upgradedRows(page.layout),
    }))
  )

  if (upgraded.type !== 'button') {
    return upgraded
  }

  const {
    label,
    address,
    action,
    color,
    styling,
    tooltip,
    arguments: values,
    ...rest
  } = upgraded as StoredButtonWidget
  const held = { label, address, action, color, styling, tooltip }

  // A button widget was stored with empty arguments whether or not anything was ever made of it,
  // so the fields a user could have set are what say there is a button here to carry over.
  const wasConfigured = Object.values(held).some((value) => value != null)
  if (upgraded.buttons.length > 0 || !wasConfigured) {
    return { ...rest, buttons: upgraded.buttons }
  }

  return { ...rest, buttons: [ButtonActionModel.parse({ ...held, arguments: values ?? {} })] }
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

A private workspace belongs to its owner alone, so they may write it whatever their access on the
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

`meta` is shared presentation state that any user with manage on the placement rewrites when they
reorder a strip. Comparing it against a stored edit would report every workspace in that strip as
having unsaved changes, for every user holding an edit, which is why it is excluded from both the
comparison and the edit itself.
*/
export function withoutMeta(data: WorkspaceData): Omit<WorkspaceData, 'meta'> {
  // Content is named rather than spread, so adding a field to a workspace's data fails to compile
  // here until it is decided whether that field is content or presentation.
  const { layout } = data
  return { layout }
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

/** Handlers a `Workspace.vue` instance exposes to whatever renders its `header-prepend` slot.

A workspace is always shown on a tab strip, on the home page or on the component it is placed on,
so the strip is what a workspace is acted on through and this is what it drives.
*/
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
  /** The widget the press landed on, which is the one the cursor carries a name for. */
  widget: Widget

  /** Everything in hand, in layout order, `widget` among it. */
  widgets: Widget[]

  /** The layout it all came out of, which is one layout since a selection is made in one. */
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

  // Whether this workspace is bound to a component, rather than sitting at the engine root. The
  // engine root contains every component, so a workspace placed there restricts nothing, and the
  // controls that narrow a choice to the placement have nothing to narrow.
  const isBound = $computed(() => scope != null && !scope.isEngine)

  /** Whether an address falls within this workspace's placement.
   *
   * A workspace at the engine root admits every component. One bound to a component admits that
   * component and its descendants. Callers use this to offer only the addresses whose records the
   * widget can actually resolve, so it must agree with what `resolveFilterAddress` produces.
   */
  function isWithinScope(address: Address | string): boolean {
    if (scope == null || scope.isEngine) {
      return true
    }

    const base = scope.toString()
    const value = address.toString()
    return value === base || value.startsWith(`${base}.`)
  }

  // Like resolveAddress, but an unset value falls back to the scope's own subtree instead of
  // staying null. Record widgets (messages, logs, alerts, particles) use this for their
  // `filter.address` field, since a widget added to a scoped workspace with no address chosen
  // yet must default to showing only the scope and its descendants, not every component.
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

  const edited = $computed(() => {
    if (data == null || workspace == null) {
      return false
    }

    return !isStructurallyEqual(withoutMeta(data), withoutMeta(workspace.data))
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

  /** A row opened to hold `widget`, as tall as that widget asks to be and no taller.

  A row is otherwise opened at the height a row of charts wants, which leaves a button or a value
  sitting at the top of a band of nothing that has to be dragged shut by hand every time.
  */
  function openedRow(widgets: Widget[], opening: Widget): WidgetRow {
    return WidgetRowModel.parse({
      widgets,
      height: widgetInfos[opening.type].options.minHeight,
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
      const minHeight = widgetInfos[widget.type].options.minHeight
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

    // Every layout is asked, since a widget is deleted by name rather than by where it sits and a
    // carousel slide holds widgets the same way the workspace does.
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

  /** Put `replacement` where the widget named `id` stands, keeping its name and its width.

  A widget turned into another kind is the same widget in the same place, so what the layout says
  about it stays as it was and only what it is changes.
  */
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

    // A drop that lands widgets back where they came from arrives at the layout already on screen,
    // which is not worth rewriting every row for, nor sending to the server as an edit.
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

    // What is picked out goes with it, so a widget dragged into a carousel slide is still the
    // widget being worked on once it arrives and Delete still has something to act on.
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

  // Widgets picked out to be acted on together, held as IDs so a layout rebuilt underneath them
  // keeps the same ones picked out.
  let selection = $ref<string[]>([])

  // Which layout they were picked out of. What is picked out belongs to one layout at a time,
  // since a selection spanning a carousel slide and the workspace around it has no one order to
  // read it in and nowhere a copy of it could land.
  let selectionLayout = $ref<string>(rootLayoutId)

  // The widget a range extends from, which is whichever one was last chosen on its own.
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

  /** Work in `layoutId` from now on, without anything in it picked out.

  A layout with nothing on it has no widget to pick out, so pressing it is the only way it can say
  that it is the one being worked in. A paste has to land somewhere, and an empty carousel slide
  that had just been pressed is the likeliest somewhere it was meant for.
  */
  function focusLayout(layoutId: string) {
    selectionLayout = layoutId
    selection = []
    selectionAnchor = null
  }

  function selectWidget(id: string, mode: SelectMode = 'replace', layoutId: string = rootLayoutId) {
    // Reaching into another layout lets go of what was picked out in the one before it, so there
    // is nothing left to extend from or toggle against.
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

  /** What is picked out, as text for the system clipboard, or null when nothing is. */
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

  /** Put the widgets `text` holds into the layout, and pick them out. Returns how many landed.

  Text that is not a copy of some widgets lands nothing, since a paste of anything else belongs to
  whatever else is on the page.
  */
  function pasteWidgets(text: string): number {
    // Widgets land beside whatever they were taken from, which is the layout that is being worked
    // in even when the paste came from another workspace entirely.
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
      // Fresh IDs, so pasting twice leaves two of everything rather than one the layout holds in
      // two places.
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

    // Landing under what is picked out puts a paste beside the thing it was taken from, rather
    // than at the far end of a workspace the user would then have to go looking down.
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

  // A widget that is deleted, or that belongs to a layout an undo replaced, cannot stay picked
  // out, so the selection follows whatever the layout actually holds. A carousel taken away takes
  // its slides with it, so the layout the selection was made in may be gone as well.
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

  async function afterFetch() {
    if (data == null) {
      data = (await workspaces.getEdit(id))?.data ?? deepClone(workspace?.data ?? null) ?? null

      // Seed the history with the loaded state so the first edit has something to undo back to.
      if (data != null) {
        history = [deepClone(data) as WorkspaceData]
        historyIndex = 0
      }
    }
  }

  // True while a workspace is being fetched and its working copy seeded, so a host can tell an
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

  // The context follows its workspace ID rather than being rebuilt for each one, so a host that
  // switches between workspaces keeps its surrounding chrome mounted. Everything derived from the
  // previous workspace has to be cleared first, since the working copy and its history belong to
  // the workspace they were loaded for.
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
    // A workspace is placed on a component or on the engine root, and its access is that
    // placement's access. A private workspace belongs to its owner alone, whatever the placement
    // says, since nobody else can see it at all.
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

  // Every workspace the caller may see, whatever it is placed on, which is what the drawer's
  // Workspaces section lists. The server does the limiting, returning the workspaces whose
  // placement the caller can view plus the private ones they own.
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

  /** Show a workspace on home.

  Home is where a workspace is looked at, so opening one goes there rather than to a page of its
  own. The workspace keeps its placement, so one bound to a component still resolves its widgets
  against that component from here.

  Naming it in the query is the whole of it. Home reads that query and puts the workspace on its
  strip if it was not already there, so a link, a sidebar click, and an action all arrive the same
  way.
  */
  async function open(id: string) {
    await navigation.push({ path: '/', query: { [workspaceQueryKey]: id } })
  }

  /** Copy a link that opens workspaces on the page a placement belongs to.

  Sharing is deliberate rather than a side effect of looking at something, because the address is
  read on arrival and taken back out of the bar. This is what puts one together on request.
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

  async function getEdit(workspaceId: string) {
    if (auth.user == null) {
      return null
    }

    try {
      return await client.get(`/api/users/${auth.user.id}/workspace-edits/${workspaceId}`, {
        parse: WorkspaceEditModel,
      })
    } catch {
      return null
    }
  }

  async function assignEdit(workspaceId: string, data: WorkspaceData) {
    return await client.put(`/api/users/${getUserId()}/workspace-edits/${workspaceId}`, {
      data: {
        // `meta` is shared, so an edit carries content only. Committing an edit must not restore
        // the tab order that was in force when the edit began.
        data: withoutMeta(data),
      },
      parse: WorkspaceEditModel,
    })
  }

  // Used by the component-scoped tab strip to learn which of several workspaces it is not
  // currently displaying still have unsaved local changes, without loading each one's full
  // workspace context.
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

      // An exported file carries the identity of where it came from. Only its name and contents
      // travel, so the import lands where the user dropped it rather than where it was made.
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

/** Spread a row's widths back over `widgetWidthSubdivisions`, without touching any widget.

`keepIndices` names widths to leave alone, either absorbing the difference into every other width
or, with `adjustMode` set to `after`, only into the ones that follow the last of them.
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
  const excessWidthUnits = totalWidthUnits - widgetWidthSubdivisions
  if (excessWidthUnits === 0) {
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

  const excessWidthUnitsPerWidget = excessWidthUnits / adjusted.length

  const resolved = [...widths]
  for (const index of adjusted) {
    resolved[index] -= excessWidthUnitsPerWidget
  }

  return resolved.map((width) => Math.round(width))
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

/** The layouts a widget holds under names of its own, or none where it holds no layouts.

The one way to reach them. Everything that walks the layouts of a workspace goes through here, so a
widget that holds pages is understood by all of it the moment it is named here, rather than by
however many places happened to remember to ask.
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

/** The name the workspace's own layout goes by, as against one belonging to a widget's page. */
export const rootLayoutId = 'root'

/** A layout a workspace holds, under the name a placement calls it by.

The workspace has one of its own, and every carousel slide anywhere inside it has another. They are
all arranged the same way, so naming them is the whole of what tells them apart.
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

A widget may carry pages that name layouts of their own, holding rows that hold further widgets, so
a copy keeping any of those names would leave two things answering to one. Everything that goes
looking by name takes whichever it finds first, which is the other one about half the time.
*/
export function withFreshIds(widget: Widget): Widget {
  const copy: Widget = { ...widget, id: v7() }

  return withPages(copy, pagesOf(copy).map(withFreshPage))
}

/** A copy of `page` under fresh IDs, all the way down, for the same reason. */
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

/** The layouts a move settles on, so they can be drawn before the move is applied.

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

Widgets in hand keep the rows they came from when the drop opens rows of its own, so a block of a
workspace taken from several rows arrives with the shape it had. A drop into an existing row has
only the one row to arrive in, so the whole selection goes there side by side. Where they arrive
need not be where they came from, since a carousel slide is arranged the same way a workspace is
and a widget travels between the two.

A null `placement` plans the removal alone, which is the layout to show while widgets are in hand
with nowhere yet chosen for them. Returns null when no layout holds any of `ids`, when the
placement names a row that is not there to drop into, or when it names a layout that a widget in
hand is itself carrying.
*/
export function planWidgetsMove(
  layouts: Map<string, WidgetRow[]>,
  ids: string[],
  placement: WidgetPlacement | null
): WidgetMovePlan | null {
  const held = new Set(ids)

  // The layout the widgets came out of. A drag holds widgets from one layout at a time, since
  // reaching into another lets go of whatever was picked out before.
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

  // What is in hand, grouped by the row each part of it came from, both in layout order. A group
  // is what becomes a row again when the drop opens rows rather than joining one.
  const groups: { row: WidgetRow; widgets: Widget[]; consumed: boolean }[] = []

  // Taking the widgets out comes first, so a placement means the same thing here as it did to the
  // hand that chose it.
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

  // A carousel cannot be dropped onto a slide of its own. The layout would then hold the widget
  // holding it, and nothing walking it would ever reach the end.
  if (layoutsWithin(carried).has(placement.layout)) {
    return null
  }

  // Arriving back where they left is the same layout twice, so the rows they are taken out of are
  // the rows they go into. Arriving somewhere else leaves the layout they left as it is.
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
        // A row the move empties is gone, which frees its ID for the row taking its place. Reusing
        // it is what lets a selection dropped back where it started read as no change at all.
        id: group.consumed ? group.row.id : v7(),
        height: group.row.height,
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
    ...groups.map((group) => group.row.height)
  )

  // Each arriving widget claims no more than an even share of the row it joins, and the widgets
  // already there give up the difference. Rejoining the row it came from works out to the widths
  // that row already had, since its share is the one it just gave up. Read across every layout,
  // since an arriving widget's own width comes from the one it left.
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

A button widget is pointed at as many components as it holds buttons, so it answers with none. The
header's shortcut is for a widget that is a view of one thing.
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

// Build a value that changes whenever any of a widget's address-bearing fields change. Used to
// detect when a user repoints a restricted stub so its lock placeholder can be cleared, since
// the redacted field the widget loaded with is not something the user could have knowingly set.
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
    values.push(widget.filter.address)
  }
  if ('particles' in widget) {
    values.push(widget.particles.map((particle) => particle.address?.toString() ?? null))
  }
  if ('buttons' in widget) {
    values.push(widget.buttons.map((button) => button.address?.toString() ?? null))
  }

  return JSON.stringify(values.map((value) => value?.toString() ?? null))
}
