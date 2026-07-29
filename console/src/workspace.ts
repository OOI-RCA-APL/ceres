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

export type ButtonWidget = Zod.infer<typeof ButtonWidgetModel>
export const ButtonWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('button'),
  name: Zod.string().catch(''),
  label: Zod.string().nullish(),
  address: AddressModel.nullish(),
  action: Zod.string().nullish(),
  arguments: Zod.record(Zod.string(), Zod.any()).catch(() => ({})),
  color: ColorModel.nullish().catch(undefined),
  styling: ButtonStylingModel.nullish().catch(undefined),
  tooltip: Zod.string().nullish().catch(undefined),
})

export type Widget = Zod.infer<typeof WidgetModel>
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
])

export type WidgetType = Widget['type']
export type WidgetInfo = (typeof widgetInfos)[keyof typeof widgetInfos]
export type WidgetComponent = (typeof widgetInfos)[WidgetType]['component']

const defaultMinHeight = 150
const defaultPaddingClass = 'q-pa-sm'

export function getWidgetInfo(type: WidgetType): WidgetInfo {
  return widgetInfos[type]
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
  button: {
    type: 'button',
    name: 'Button',
    model: ButtonWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetButton.vue')),
    settingsComponent: defineAsyncComponent(
      () => import('@/components/WorkspaceWidgetButtonSettings.vue')
    ),
    options: widgetOptions({
      minHeight: 50,
      fullHeight: false,
    }),
  },
} as const

export type WidgetRow = Zod.infer<typeof WidgetRowModel>
export const WidgetRowModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  height: Zod.number().catch(250),
  collapsed: Zod.boolean().catch(false),
  widgets: safeArrayOf(WidgetModel),
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

export type WorkspaceDataInput = Zod.input<typeof WorkspaceDataModel>
export type WorkspaceData = Zod.infer<typeof WorkspaceDataModel>
export const WorkspaceDataModel = Zod.object({
  layout: WidgetRowModel.array().catch(() => []),
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

/** Handlers a `Workspace.vue` instance exposes to whatever renders its `header-prepend` slot,
so a scoped workspace's tab strip can drive the same actions the standalone header would.
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
  widget: Widget
}

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

  function insertWidget(widget: Widget, row: number, column: number = 0) {
    if (data == null) {
      return
    }

    row = Math.min(data.layout.length, row)
    const widgets = [...(data.layout[row]?.widgets ?? [])]
    widgets.splice(column, 0, widget)
    widget.width = Math.min(widgetWidthSubdivisions / widgets.length, widget.width)
    resolveWidgetWidths(widgets, widgets.indexOf(widget))

    if (row < 0) {
      data.layout = [WidgetRowModel.parse({ widgets }), ...data.layout]
    } else if (data.layout[row] == null) {
      data.layout = [...data.layout, WidgetRowModel.parse({ widgets })]
    } else {
      const rowObject = data.layout[row]
      const minHeight = widgetInfos[widget.type].options.minHeight
      if (rowObject.height < minHeight) {
        rowObject.height = minHeight
      }

      rowObject.widgets = widgets
    }
  }

  function addWidget(type: WidgetType, row: number, column: number = 0) {
    if (data == null) {
      return null
    }

    const widget = widgetInfos[type].model.parse({ type })
    insertWidget(widget, row, column)

    return widget
  }

  function deleteWidget(id: string) {
    if (data == null) {
      return null
    }

    for (const [i, row] of data.layout.entries()) {
      const widget = row.widgets.find((widget) => widget.id === id) ?? null
      if (widget != null) {
        row.widgets = row.widgets.filter((widget) => widget.id !== id)
        resolveWidgetWidths(row.widgets)

        if (row.widgets.length === 0) {
          data.layout = data.layout.filter((_, index) => index !== i)
        }

        return widget
      }
    }

    return null
  }

  function getWidget(id: string) {
    return data?.layout.flatMap((row) => row.widgets).find((widget) => widget.id === id) ?? null
  }

  function getWidgetPosition(id: string): [row: number, column: number] | null {
    for (const [rowIndex, row] of data?.layout.entries() ?? []) {
      const columnIndex = row.widgets.findIndex((widget) => widget.id === id)
      if (columnIndex !== -1) {
        return [rowIndex, columnIndex]
      }
    }

    return null
  }

  function getWidgetAt(row: number, column: number) {
    return data?.layout[row]?.widgets[column] ?? null
  }

  function moveWidget(id: string, placement: WidgetPlacement) {
    if (data == null) {
      return null
    }

    const plan = planWidgetMove(data.layout, id, placement)
    if (plan == null) {
      return null
    }

    const widgets = new Map(
      data.layout.flatMap((row) => row.widgets).map((widget) => [widget.id, widget])
    )

    // A drop that lands a widget back where it came from arrives at the layout already on screen,
    // which is not worth rewriting every row for, nor sending to the server as an edit.
    if (planIsCurrent(plan, data.layout)) {
      return widgets.get(id) ?? null
    }

    for (const [widgetId, width] of Object.entries(plan.widths)) {
      const widget = widgets.get(widgetId)
      if (widget != null) {
        widget.width = width
      }
    }

    data.layout = plan.rows.map((row) => ({
      id: row.id,
      height: row.height,
      collapsed: row.collapsed,
      widgets: row.widgets
        .map((widgetId) => widgets.get(widgetId))
        .filter((widget) => widget != null),
    }))

    return widgets.get(id) ?? null
  }

  function duplicateWidget(id: string, toRow: number, toColumn: number) {
    const widget = getWidget(id)
    if (widget == null) {
      return null
    }

    const copy: Widget = deepClone(widget)
    copy.id = v7()

    insertWidget(copy, toRow, toColumn)
    return copy
  }

  watchEffect(() => {
    if (data == null) {
      return
    }

    if (data.layout.some((row) => row.widgets.length === 0)) {
      data.layout = data.layout.filter((row) => row.widgets.length > 0)
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
    getWidgetAt,
    getWidgetPosition,
    insertWidget,
    addWidget,
    deleteWidget,
    moveWidget,
    duplicateWidget,
    drag: null as Drag | null,
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

`keepIndex` names a width to leave alone, either absorbing the difference into every other width
or, with `adjustMode` set to `after`, only into the ones that follow it.
*/
export function resolveWidths(
  widths: number[],
  keepIndex?: number,
  adjustMode: 'after' | 'other' = 'other'
): number[] {
  if (widths.length === 0) {
    return []
  }
  if (keepIndex != null && keepIndex < 0) {
    keepIndex = undefined
  }

  const totalWidthUnits = widths.reduce((sum, current) => sum + current, 0)
  const excessWidthUnits = totalWidthUnits - widgetWidthSubdivisions
  if (excessWidthUnits === 0) {
    return [...widths]
  }

  const indices = widths.map((_, index) => index)

  let adjusted: number[]
  if (keepIndex == null) {
    adjusted = indices
  } else {
    if (adjustMode === 'after') {
      adjusted = indices.slice(keepIndex + 1)
    } else {
      adjusted = indices.filter((index) => index !== keepIndex)
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
  keepIndex?: number,
  adjustMode: 'after' | 'other' = 'other'
) {
  const resolved = resolveWidths(
    widgets.map((widget) => widget.width),
    keepIndex,
    adjustMode
  )

  for (const [index, widget] of widgets.entries()) {
    if (widget.width !== resolved[index]) {
      widget.width = resolved[index]
    }
  }
}

/** Where a widget in hand would land.

Both indices read against the layout with that widget already taken out of it, which is the layout
its owner is looking at while the drag is in progress.
*/
export type WidgetPlacement = {
  /** Row to drop into, or the index the new row takes when `column` is null. */
  row: number

  /** Insertion index within that row, or null to open a row of its own. */
  column: number | null
}

/** The layout a move settles on, in widget IDs, so it can be drawn before it is applied. */
export type WidgetMovePlan = {
  rows: {
    id: string
    height: number
    collapsed: boolean
    widgets: string[]
  }[]

  /** The widths the move settles on, by widget ID. Widgets left at their own width are absent. */
  widths: Record<string, number>
}

/** Whether a plan describes the layout that is already there, down to the widths. */
function planIsCurrent(plan: WidgetMovePlan, layout: WidgetRow[]): boolean {
  if (plan.rows.length !== layout.length) {
    return false
  }

  for (const [index, row] of plan.rows.entries()) {
    const current = layout[index]
    if (
      row.id !== current.id ||
      row.height !== current.height ||
      row.collapsed !== current.collapsed ||
      row.widgets.length !== current.widgets.length
    ) {
      return false
    }

    for (const [position, widgetId] of row.widgets.entries()) {
      if (widgetId !== current.widgets[position].id) {
        return false
      }
    }
  }

  const widths = new Map(
    layout.flatMap((row) => row.widgets).map((widget) => [widget.id, widget.width])
  )

  return Object.entries(plan.widths).every(([widgetId, width]) => widths.get(widgetId) === width)
}

/** Work out the layout that moving one widget to `placement` produces, changing nothing.

A null `placement` plans the removal alone, which is the layout to show while a widget is in hand
with nowhere yet chosen for it. Returns null when the layout holds no such widget, or when the
placement names a row that is not there to drop into.
*/
export function planWidgetMove(
  layout: WidgetRow[],
  id: string,
  placement: WidgetPlacement | null
): WidgetMovePlan | null {
  let fromRow = -1
  let fromColumn = -1
  for (const [index, row] of layout.entries()) {
    const column = row.widgets.findIndex((widget) => widget.id === id)
    if (column !== -1) {
      fromRow = index
      fromColumn = column
      break
    }
  }

  if (fromRow === -1) {
    return null
  }

  const sourceRow = layout[fromRow]
  const widget = sourceRow.widgets[fromColumn]
  const widths: Record<string, number> = {}

  // Taking the widget out comes first, so a placement means the same thing here as it did to the
  // hand that chose it.
  let rows = layout.map((row) => ({
    id: row.id,
    height: row.height,
    collapsed: row.collapsed,
    widgets: row.widgets.map((current) => current.id),
  }))
  rows[fromRow].widgets.splice(fromColumn, 1)

  const remaining = sourceRow.widgets.filter((_, index) => index !== fromColumn)
  const remainingWidths = resolveWidths(remaining.map((current) => current.width))
  for (const [index, current] of remaining.entries()) {
    widths[current.id] = remainingWidths[index]
  }

  const wasAlone = remaining.length === 0
  rows = rows.filter((row) => row.widgets.length > 0)

  if (placement == null) {
    return { rows, widths }
  }

  if (placement.column == null) {
    // A widget that had a row to itself and is dropped back at that row's seam belongs to the row
    // it came from, which keeps the move from reading as an edit.
    const isSourceRow = wasAlone && placement.row === fromRow

    rows.splice(placement.row, 0, {
      id: isSourceRow ? sourceRow.id : v7(),
      height: sourceRow.height,
      collapsed: sourceRow.collapsed,
      widgets: [id],
    })
    widths[id] = widgetWidthSubdivisions

    return { rows, widths }
  }

  const destinationRow = rows[placement.row] ?? null
  if (destinationRow == null) {
    return null
  }

  destinationRow.widgets.splice(placement.column, 0, id)
  destinationRow.height = Math.max(destinationRow.height, sourceRow.height)

  // The widget claims no more than an even share of the row it joins, and the widgets already
  // there give up the difference. Rejoining the row it came from works out to the widths that row
  // already had, since its share is the one it just gave up.
  const currentWidths = new Map(
    layout.flatMap((row) => row.widgets).map((current) => [current.id, current.width])
  )
  const claimed = Math.min(widgetWidthSubdivisions / destinationRow.widgets.length, widget.width)
  const resolved = resolveWidths(
    destinationRow.widgets.map((widgetId) =>
      widgetId === id ? claimed : currentWidths.get(widgetId) ?? 0
    ),
    placement.column
  )
  for (const [index, widgetId] of destinationRow.widgets.entries()) {
    widths[widgetId] = resolved[index]
  }

  return { rows, widths }
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

  return JSON.stringify(values.map((value) => value?.toString() ?? null))
}
