import { defineStore } from 'pinia'
import { v4 } from 'uuid'
import { computed, inject, MaybeRef, provide, reactive, unref, watchEffect } from 'vue'
import Zod from 'zod'

import { AddressModel, AddressSelectorModel } from '@/api/address'
import { ProcedureTypeModel } from '@/api/components'
import { useSettings } from '@/api/settings'
import { getter } from '@/getter'
import { useNavigation } from '@/navigation'
import { workspaceInjectionKey } from '@/symbols'

export type BaseWidget = Zod.infer<typeof BaseWidgetModel>
const BaseWidgetModel = Zod.object({
  id: Zod.string().default(() => v4()),
  name: Zod.string(),
  width: Zod.number().default(100), // Percentage of row width, not pixels.
})

export type MessagesWidget = Zod.infer<typeof MessagesWidgetModel>
export const MessagesWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('messages'),
  name: Zod.string().default('Messages'),
  filter: Zod.object({
    after: Zod.string().optional(),
    before: Zod.string().optional(),
    address: AddressSelectorModel.optional(),
    direction: Zod.string().optional(),
    content_prefix: Zod.string().optional(),
    content_contains: Zod.string().optional(),
  }).default(() => ({})),
  commandAddress: AddressModel.nullable().default(null),
  commandText: Zod.string().default(''),
  commandHistory: Zod.string()
    .array()
    .default(() => []),
  commandHistoryIndex: Zod.number().nullable().default(null),
})

export type AlertsWidget = Zod.infer<typeof AlertsWidgetModel>
export const AlertsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('alerts'),
  name: Zod.string().default('Alerts'),
  filter: Zod.object({
    after: Zod.string().optional(),
    before: Zod.string().optional(),
    address: AddressSelectorModel.optional(),
    level: Zod.string().optional(),
    code_prefix: Zod.string().optional(),
    code_contains: Zod.string().optional(),
  }).default(() => ({})),
})

export type LogsWidget = Zod.infer<typeof LogsWidgetModel>
export const LogsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('logs'),
  name: Zod.string().default('Logs'),
  filter: Zod.object({
    after: Zod.string().optional(),
    before: Zod.string().optional(),
    address: AddressSelectorModel.optional(),
    level: Zod.string().optional(),
    content_prefix: Zod.string().optional(),
    content_contains: Zod.string().optional(),
  }).default(() => ({})),
})

export type ProceduresWidget = Zod.infer<typeof ProceduresWidgetModel>
export const ProceduresWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('procedures'),
  name: Zod.string().default('Procedures'),
  procedureAddress: AddressModel.nullable().default(null),
  procedureType: ProcedureTypeModel.default('action'),
  procedureName: Zod.string().nullable().default(null),
})

export type UIWidget = Zod.infer<typeof UIWidgetModel>
export const UIWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('ui'),
  name: Zod.string().default('UI'),
  interfaceAddress: AddressModel.nullable().default(null),
})

export type Widget = Zod.infer<typeof WidgetModel>
export const WidgetModel = Zod.discriminatedUnion('type', [
  MessagesWidgetModel,
  AlertsWidgetModel,
  LogsWidgetModel,
  ProceduresWidgetModel,
  UIWidgetModel,
])

export type WidgetType = Widget['type']

export type WidgetRow = Zod.infer<typeof WidgetRowModel>
export const WidgetRowModel = Zod.object({
  id: Zod.string().default(() => v4()),
  height: Zod.number().default(250),
  widgets: WidgetModel.array().default(() => []),
  collapsed: Zod.boolean().default(false),
})

export type WorkspaceData = Zod.infer<typeof WorkspaceModel>
export const WorkspaceModel = Zod.object({
  name: Zod.string(),
  layout: WidgetRowModel.array().default(() => []),
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

  const widgetModelMapping = {
    messages: MessagesWidgetModel,
    alerts: AlertsWidgetModel,
    logs: LogsWidgetModel,
    procedures: ProceduresWidgetModel,
    ui: UIWidgetModel,
  } as const

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

    const widget = widgetModelMapping[type].parse({ type })
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
      const destinationRow = {
        id: v4(),
        height: sourceRow.height,
        widgets: [widget],
        collapsed: false,
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

  function del(name: string) {
    settings.workspaces = settings.workspaces.filter((current) => current.name !== name)
  }

  function create(name?: string | null) {
    name = getUniqueName(name)
    let workspace = get(name)
    if (workspace == null) {
      workspace = WorkspaceModel.parse({
        name,
        layout: [
          { height: 250, widgets: [{ type: 'messages' }] },
          { height: 250, widgets: [{ type: 'alerts' }] },
          { height: 250, widgets: [{ type: 'logs' }] },
          { height: 150, widgets: [{ type: 'procedures' }] },
        ],
      } as Zod.input<typeof WorkspaceModel>)

      settings.workspaces = [...settings.workspaces, workspace].sort((left, right) =>
        left.name.localeCompare(right.name)
      )
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

    const copied = { ...workspace, name: getUniqueName(newName ?? name) }
    settings.workspaces = [...settings.workspaces, copied]
    return copied
  }

  async function open(name: string) {
    const workspace = get(name)
    if (workspace != null) {
      await navigation.go(`/workspaces/${name}`)
      return workspace
    }

    return null
  }

  return {
    all: computed(() => settings.workspaces),
    get: getter(
      computed(() => settings.workspaces),
      get
    ),
    create: getter(
      computed(() => settings.workspaces),
      create
    ),
    rename,
    delete: del,
    duplicate,
    open,
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
