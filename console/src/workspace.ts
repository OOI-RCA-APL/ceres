import { useQuery } from '@tanstack/vue-query'
import { useEventListener } from '@vueuse/core'
import { debounce } from 'lodash-es'
import { defineStore } from 'pinia'
import { exportFile as download } from 'quasar'
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
import { Address, AddressModel, AddressSelector, AddressSelectorModel } from '@/api/address'
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

export type UIWidget = Zod.infer<typeof UIWidgetModel>
export const UIWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('ui'),
  name: Zod.string().catch('UI'),
  interfaceAddress: AddressModel.nullish(),
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
  UIWidgetModel,
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
    component: () => defineAsyncComponent(() => import('@/components/WorkspaceWidgetAlerts.vue')),
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
  ui: {
    type: 'ui',
    name: 'UI View',
    model: UIWidgetModel,
    component: defineAsyncComponent(() => import('@/components/WorkspaceWidgetUi.vue')),
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

/** Address of the engine root, the placement every workspace not bound to a component sits on. */
export const engineRoot = '~'

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
  row: number
  column: number
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

  function isEnginePlaced(): boolean {
    return workspace != null && workspace.scope.toString() === engineRoot
  }

  /** Whether the caller may edit and manage this workspace, which are the same right. */
  function isWritable(): boolean {
    if (workspace == null) {
      return false
    }
    if (workspace.owner_id != null) {
      return workspace.owner_id === auth.user?.id
    }
    if (isEnginePlaced()) {
      // Engine-level manage comes from an all-target grant, which the console models as manage
      // on every component rather than as a level on the root itself.
      return auth.user?.admin === true
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
    return data != null && workspace != null && !isStructurallyEqual(data, workspace?.data)
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

  function moveWidget(id: string, toRow: number, toColumn?: number | null) {
    if (data == null) {
      return null
    }

    const position = getWidgetPosition(id)
    if (position == null) {
      return null
    }
    const [fromRow, fromColumn] = position

    const sourceRow = data.layout[fromRow] ?? null
    if (sourceRow == null) {
      return null
    }

    const widget = sourceRow.widgets[fromColumn] ?? null
    if (widget == null) {
      return null
    }

    sourceRow.widgets = sourceRow.widgets.filter((_, index) => index !== fromColumn)

    // If there is no column specified, create a new row.
    if (toColumn == null) {
      let layout = [...data.layout]
      const destinationRow: WidgetRow = {
        id: v7(),
        height: sourceRow.height,
        widgets: [widget],
        collapsed: sourceRow.collapsed,
      }

      layout.splice(toRow, 0, destinationRow)
      layout = layout.filter((row) => row != null && row.widgets.length > 0)
      data.layout = layout

      resolveWidgetWidths(sourceRow.widgets)
      resolveWidgetWidths(destinationRow.widgets)
      return widget
    }

    const destinationRow = data.layout[toRow] ?? null
    if (destinationRow == null) {
      resolveWidgetWidths(sourceRow.widgets)
      return null
    }

    destinationRow.widgets = [...destinationRow.widgets]
    destinationRow.widgets.splice(toColumn, 0, widget)
    destinationRow.widgets = destinationRow.widgets.filter((current) => current != null)
    destinationRow.height = Math.max(destinationRow.height, sourceRow.height)

    resolveWidgetWidths(sourceRow.widgets)
    widget.width = Math.min(widgetWidthSubdivisions / destinationRow.widgets.length, widget.width)
    resolveWidgetWidths(destinationRow.widgets, destinationRow.widgets.indexOf(widget))

    data.layout = data.layout.filter((row) => row != null && row.widgets.length > 0)

    return widget
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
    owner: computed(() => workspace?.owner_id ?? null),
    isPrivate: computed(() => workspace?.owner_id != null),
    isEnginePlaced: computed(() => isEnginePlaced()),
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

      return isEnginePlaced() ? auth.user != null : access.canView(workspace.scope.toString())
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

  // The drawer's Workspaces section only lists global workspaces. Scoped workspaces are
  // reached from their scope component's details page instead.
  // The server already limits this to what the caller may see, which is the workspaces whose
  // placement they can view plus the private ones they own.
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

  async function open(id: string) {
    await navigation.go(`/workspaces/${id}`)
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
        data,
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

  async function importFiles() {
    const files = await selectFile({ multiple: true, accept: 'application/json' })
    if (files == null) {
      return null
    }

    const imported: Workspace[] = []

    for (const file of files) {
      const parsed = JSON.parse(await file.text())
      if (parsed === undefined) {
        notify.error(`Import of '${file.name}' failed. Invalid JSON.`)
        continue
      }

      const { data: workspace, error } = WorkspaceModel.safeParse(parsed)
      if (error != null) {
        notify.error(`Import of '${file.name}' failed. Invalid workspace file. ${error.message}`)
        continue
      }

      const created = await create({
        name: workspace.name,
        data: workspace.data,
      })
      imported.push(created)
    }

    if (imported.length == 0) {
      notify.success(`${imported.length} workspace(s) imported successfully.`)
    }

    return imported
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
    delete: del,
    getEdit,
    getEdits,
    assignEdit,
    discardEdit,
    importFiles,
    exportFile,
  }
})

export const widgetWidthSubdivisions = 120
export const minWidgetWidthPixels = 100

export function resolveWidgetWidths(
  widgets: Widget[],
  keepIndex?: number,
  adjustMode: 'after' | 'other' = 'other'
) {
  if (widgets.length === 0) {
    return
  }
  if (keepIndex != null && keepIndex < 0) {
    keepIndex = undefined
  }

  const totalWidthUnits = widgets.reduce((sum, current) => sum + current.width, 0)
  const excessWidthUnits = totalWidthUnits - widgetWidthSubdivisions
  if (excessWidthUnits === 0) {
    return
  }

  let adjusted: Widget[]
  if (keepIndex == null) {
    adjusted = widgets
  } else {
    if (adjustMode === 'after') {
      adjusted = widgets.slice(keepIndex + 1)
    } else {
      adjusted = widgets.filter((_, index) => index !== keepIndex)
    }
  }

  const excessWidthUnitsPerWidget = excessWidthUnits / adjusted.length

  for (const widget of adjusted) {
    widget.width -= excessWidthUnitsPerWidget
  }

  for (const widget of widgets) {
    if (Math.round(widget.width) !== widget.width) {
      widget.width = Math.round(widget.width)
    }
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
  if ('interfaceAddress' in widget) {
    values.push(widget.interfaceAddress)
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

