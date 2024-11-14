import { defineStore } from 'pinia'
import { exportFile as download } from 'quasar'
import { v4 } from 'uuid'
import { computed, inject, MaybeRef, provide, reactive, unref, watchEffect } from 'vue'
import Zod from 'zod'

import { DateTimeModel } from './api/shared'

import { AddressModel, AddressSelectorModel } from '@/api/address'
import { AlertFilterModel } from '@/api/alerts'
import { ProcedureTypeModel } from '@/api/components'
import { LogEntryFilterModel } from '@/api/log-entries'
import { MessageFilterModel } from '@/api/messages'
import { ParticleFilterModel } from '@/api/particles'
import { useSettings } from '@/api/settings'
import { getter } from '@/getter'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { workspaceInjectionKey } from '@/symbols'
import { safeArrayOf, selectFile } from '@/utilities'

export type BaseWidget = Zod.infer<typeof BaseWidgetModel>
const BaseWidgetModel = Zod.object({
  id: Zod.string().catch(() => v4()),
  name: Zod.string(),
  width: Zod.number().catch(100), // Percentage of row width, not pixels.
})

export type MessagesWidget = Zod.infer<typeof MessagesWidgetModel>
export const MessagesWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('messages'),
  name: Zod.string().catch('Messages'),
  filter: MessageFilterModel.catch(() => ({})),
  commandAddress: AddressModel.nullish(),
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
  name: Zod.string().catch('Series'),
  field: Zod.string().nullish(),
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
  before: DateTimeModel.nullish(),
  timespan: Zod.union([Zod.number(), Zod.string()]).catch(60 * 60),
  particles: safeArrayOf(ChartWidgetParticleModel),
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
])

export type WidgetType = Widget['type']
export type WidgetInfo = (typeof widgetInfos)[keyof typeof widgetInfos]

export const widgetInfos = {
  messages: {
    type: 'messages',
    name: 'Messages View',
    model: MessagesWidgetModel,
  },
  particles: {
    type: 'particles',
    name: 'Particles View',
    model: ParticlesWidgetModel,
  },
  alerts: {
    type: 'alerts',
    name: 'Alerts View',
    model: AlertsWidgetModel,
  },
  logs: {
    type: 'logs',
    name: 'Logs View',
    model: LogsWidgetModel,
  },
  procedures: {
    type: 'procedures',
    name: 'Procedures View',
    model: ProceduresWidgetModel,
  },
  ui: {
    type: 'ui',
    name: 'UI View',
    model: UIWidgetModel,
  },
  chart: {
    type: 'chart',
    name: 'Chart',
    model: ChartWidgetModel,
  },
} as const

export type WidgetRow = Zod.infer<typeof WidgetRowModel>
export const WidgetRowModel = Zod.object({
  id: Zod.string().catch(() => v4()),
  height: Zod.number().catch(250),
  collapsed: Zod.boolean().catch(false),
  widgets: safeArrayOf(WidgetModel),
})

export type WorkspaceInfo = Zod.infer<typeof WorkspaceModel>
export const WorkspaceModel = Zod.object({
  name: Zod.string(),
  layout: WidgetRowModel.array().catch(() => []),
})

export type WorkspaceContext = ReturnType<typeof createWorkspaceContext>

export type WorkspaceContextOptions = {
  name: MaybeRef<string>
}

export type Drag = {
  widget: Widget
  row: number
  column: number
}

function createWorkspaceContext(options: WorkspaceContextOptions) {
  const workspaces = useWorkspaces()
  const name = $computed(() => unref(options.name))
  const workspace = $computed(() => workspaces.get(unref(options.name)))

  function create() {
    return workspaces.create(name)
  }

  function rename(newName: string) {
    return workspaces.rename(name, newName)
  }

  function duplicate(newName?: string | null) {
    return workspaces.duplicate(name, newName)
  }

  function del() {
    workspaces.delete(name)
  }

  function insertWidget(widget: Widget, row: number, column: number = 0) {
    if (workspace == null) {
      return
    }

    row = Math.min(workspace.layout.length, row)
    const widgets = [...(workspace.layout[row]?.widgets ?? [])]
    widgets.splice(column, 0, widget)
    widget.width = Math.min(100 / widgets.length, widget.width)
    resolveWidgetWidths(widgets, widgets.indexOf(widget))

    if (row < 0) {
      workspace.layout = [WidgetRowModel.parse({ widgets }), ...workspace.layout]
    } else if (workspace.layout[row] == null) {
      workspace.layout = [...workspace.layout, WidgetRowModel.parse({ widgets })]
    } else {
      workspace.layout[row].widgets = widgets
    }
  }

  function addWidget(type: WidgetType, row: number, column: number = 0) {
    if (workspace == null) {
      return null
    }

    const widget = widgetInfos[type].model.parse({ type })
    insertWidget(widget, row, column)

    return widget
  }

  function deleteWidget(id: string) {
    if (workspace == null) {
      return null
    }

    for (const [i, row] of workspace.layout.entries()) {
      const widget = row.widgets.find((widget) => widget.id === id) ?? null
      if (widget != null) {
        row.widgets = row.widgets.filter((widget) => widget.id !== id)
        resolveWidgetWidths(row.widgets)

        if (row.widgets.length === 0) {
          workspace.layout = workspace.layout.filter((_, index) => index !== i)
        }

        return widget
      }
    }

    return null
  }

  function getWidget(id: string) {
    return (
      workspace?.layout.flatMap((row) => row.widgets).find((widget) => widget.id === id) ?? null
    )
  }

  function getWidgetPosition(id: string): [row: number, column: number] | null {
    for (const [rowIndex, row] of workspace?.layout.entries() ?? []) {
      const columnIndex = row.widgets.findIndex((widget) => widget.id === id)
      if (columnIndex !== -1) {
        return [rowIndex, columnIndex]
      }
    }

    return null
  }

  function getWidgetAt(row: number, column: number) {
    return workspace?.layout[row]?.widgets[column] ?? null
  }

  function moveWidget(id: string, toRow: number, toColumn?: number | null) {
    if (workspace == null) {
      return null
    }

    const position = getWidgetPosition(id)
    if (position == null) {
      return null
    }
    const [fromRow, fromColumn] = position

    const sourceRow = workspace.layout[fromRow] ?? null
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
      let layout = [...workspace.layout]
      const destinationRow: WidgetRow = {
        id: v4(),
        height: sourceRow.height,
        widgets: [widget],
        collapsed: sourceRow.collapsed,
      }

      layout.splice(toRow, 0, destinationRow)
      layout = layout.filter((row) => row != null && row.widgets.length > 0)
      workspace.layout = layout

      resolveWidgetWidths(sourceRow.widgets)
      resolveWidgetWidths(destinationRow.widgets)
      return widget
    }

    const destinationRow = workspace.layout[toRow] ?? null
    if (destinationRow == null) {
      resolveWidgetWidths(sourceRow.widgets)
      return null
    }

    destinationRow.widgets = [...destinationRow.widgets]
    destinationRow.widgets.splice(toColumn, 0, widget)
    destinationRow.widgets = destinationRow.widgets.filter((current) => current != null)
    destinationRow.height = Math.max(destinationRow.height, sourceRow.height)

    resolveWidgetWidths(sourceRow.widgets)
    widget.width = Math.min(100 / destinationRow.widgets.length, widget.width)
    resolveWidgetWidths(destinationRow.widgets, destinationRow.widgets.indexOf(widget))

    workspace.layout = workspace.layout.filter((row) => row != null && row.widgets.length > 0)

    return widget
  }

  function duplicateWidget(id: string, toRow: number, toColumn: number) {
    const widget = getWidget(id)
    if (widget == null) {
      return null
    }

    const copy: Widget = JSON.parse(JSON.stringify(widget))
    copy.id = v4()

    insertWidget(copy, toRow, toColumn)
    return copy
  }

  watchEffect(() => {
    if (workspace == null) {
      return
    }

    if (workspace.layout.some((row) => row.widgets.length === 0)) {
      workspace.layout = workspace.layout.filter((row) => row.widgets.length > 0)
    }
  })

  return reactive({
    name: computed(() => unref(options.name)),
    data: computed(() => workspaces.get(unref(options.name))),
    create,
    duplicate,
    delete: del,
    rename,
    getWidget,
    getWidgetAt,
    getWidgetPosition,
    insertWidget,
    addWidget,
    deleteWidget,
    moveWidget,
    duplicateWidget,
    drag: null as Drag | null,
  })
}

export function provideWorkspace(options: WorkspaceContextOptions) {
  const context = createWorkspaceContext(options)
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
  const notify = useNotify()

  const settings = useSettings()

  function getUniqueName(name?: string | null) {
    let base = name ?? 'Workspace'
    if (name == null) {
      name = base
    }

    let number: number
    const match = name.match(/\(\d+\)$/)?.[0]
    if (match != null) {
      base = name.slice(0, -match.length).trimEnd()
      number = Number(match.slice(1, -1))
    } else {
      number = 1
    }

    while (get(name) != null) {
      name = `${base} (${number})`
      number++
    }

    return name
  }

  function get(name: string) {
    return settings.workspaces.find((current) => current.name === name) ?? null
  }

  function add(workspace: WorkspaceInfo, rename?: string | null) {
    workspace.name = getUniqueName(rename ?? workspace.name)
    settings.workspaces = [...settings.workspaces, workspace].sort((left, right) =>
      left.name.localeCompare(right.name)
    )

    return workspace
  }

  function create(name?: string | null) {
    name = getUniqueName(name)
    let workspace = get(name)
    if (workspace == null) {
      workspace = WorkspaceModel.parse({
        name,
        layout: [
          { height: 250, widgets: [{ type: 'messages' }] },
          { height: 200, widgets: [{ type: 'particles' }] },
          { height: 200, widgets: [{ type: 'alerts' }] },
          { height: 200, widgets: [{ type: 'logs' }] },
          { height: 150, widgets: [{ type: 'procedures' }] },
        ],
      } as Zod.input<typeof WorkspaceModel>)

      add(workspace)
    }

    return workspace
  }

  function rename(oldName: string, newName: string) {
    const workspace = get(oldName)
    if (workspace != null && workspace.name !== newName) {
      workspace.name = getUniqueName(newName)
      return workspace
    }

    return workspace
  }

  function duplicate(name: string, newName?: string | null) {
    const workspace = get(name)
    if (workspace == null) {
      return null
    }

    const copy = JSON.parse(JSON.stringify(workspace))
    add(copy, newName)
    return copy
  }

  async function open(name: string) {
    const workspace = get(name)
    if (workspace != null) {
      await navigation.go(`/workspaces/${name}`)
      return workspace
    }

    return null
  }

  function del(name: string) {
    const index = settings.workspaces.findIndex((current) => current.name === name)
    if (index === -1) {
      return
    }

    settings.workspaces = settings.workspaces.filter((_, i) => i !== index)
  }

  function exportFile(name: string) {
    const workspace = get(name)
    if (workspace == null) {
      notify.error('Workspace not found.')
      return
    }

    download(`${name}.workspace.json`, JSON.stringify(workspace, null, 2))
  }

  async function importFiles() {
    const files = await selectFile({ multiple: true, accept: 'application/json' })
    if (files == null) {
      return null
    }

    const imported: WorkspaceInfo[] = []

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

      add(workspace)
      imported.push(workspace)
    }

    if (imported.length == 0) {
      notify.success(`${imported.length} workspace(s) imported successfully.`)
    }

    return imported
  }

  return {
    all: computed(() => settings.workspaces),
    get: getter(
      computed(() => settings.workspaces),
      get
    ),
    add,
    create,
    rename,
    duplicate,
    open,
    delete: del,
    exportFile,
    importFiles,
  }
})

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

  const totalWidthPercentage = widgets.reduce((sum, current) => sum + current.width, 0)
  const excessWidthPercentage = totalWidthPercentage - 100
  if (excessWidthPercentage === 0) {
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

  const excessWidthPerWidget = excessWidthPercentage / adjusted.length

  for (const widget of adjusted) {
    widget.width -= excessWidthPerWidget
  }
}
