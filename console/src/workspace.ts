import { AddressModel, AddressSelector } from '@/api/address'
import { getter } from '@/getter'
import { useNavigation } from '@/navigation'
import { usePersisted } from '@/persistence'
import { workspaceContextInjectionKey } from '@/symbols'
import { defineStore } from 'pinia'
import { v4 } from 'uuid'
import { computed, inject, MaybeRef, provide, reactive, unref, watchEffect } from 'vue'
import Zod from 'zod'

export type BaseWidget = Zod.infer<typeof BaseWidgetModel>
const BaseWidgetModel = Zod.object({
  id: Zod.string().default(() => v4()),
  name: Zod.string(),
  width: Zod.number().default(250),
})

export type MessagesWidget = Zod.infer<typeof MessagesWidgetModel>
export const MessagesWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('messages'),
  name: Zod.string().default('Messages'),
  filter: Zod.object({
    after: Zod.string().optional(),
    before: Zod.string().optional(),
    address: Zod.string().transform(AddressSelector.parse).optional(),
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
})

export type LogsWidget = Zod.infer<typeof LogsWidgetModel>
export const LogsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('logs'),
  name: Zod.string().default('Logs'),
})

export type ProceduresWidget = Zod.infer<typeof ProceduresWidgetModel>
export const ProceduresWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('procedures'),
  name: Zod.string().default('Procedures'),
})

export type UIWidget = Zod.infer<typeof UIWidgetModel>
export const UIWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('ui'),
  name: Zod.string().default('UI'),
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

export const WidgetRowModel = Zod.object({
  height: Zod.number().default(250),
  widgets: WidgetModel.array().default(() => []),
})

export type WorkspaceData = Zod.infer<typeof WidgetModel>
export const WorkspaceDataModel = Zod.object({
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

  function copy(newName?: string | null) {
    return workspaces.copy(name, newName)
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

  function createWidget(type: WidgetType, row: number, column: number = 0) {
    if (workspace == null) {
      return null
    }

    row = Math.max(0, Math.min(workspace.layout.length, row))
    const widget = widgetModelMapping[type].parse({ type })
    const widgets = [...(workspace.layout[row]?.widgets ?? [])]
    widgets.splice(column, 0, widget)

    if (workspace.layout[row] == null) {
      workspace.layout.push({ height: 250, widgets })
    } else {
      workspace.layout[row].widgets = widgets
    }

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

    if (toColumn == null) {
      let layout = [...workspace.layout]
      layout.splice(toRow, 0, { height: 250, widgets: [widget] })
      layout = layout.filter((row) => row != null && row.widgets.length > 0)
      workspace.layout = layout
      return widget
    }

    const destinationRow = workspace.layout[toRow] ?? null
    if (destinationRow == null) {
      return null
    }

    destinationRow.widgets = [...destinationRow.widgets]
    destinationRow.widgets.splice(toColumn, 0, widget)
    destinationRow.widgets = destinationRow.widgets.filter((current) => current != null)

    workspace.layout = workspace.layout.filter((row) => row != null && row.widgets.length > 0)

    return widget
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
    workspace: computed(() => workspaces.get(unref(options.name))),
    create,
    copy,
    delete: del,
    rename,
    getWidget,
    getWidgetAt,
    getWidgetPosition,
    createWidget,
    deleteWidget,
    moveWidget,
    drag: null as Drag | null,
  })
}

export function provideWorkspaceContext(options: WorkspaceContextOptions) {
  const context = createWorkspaceContext(options)
  provide(workspaceContextInjectionKey, context)
  return context
}

export function useWorkspaceContext() {
  return inject(workspaceContextInjectionKey) ?? null
}

export const useWorkspaces = defineStore('workspaces', () => {
  const navigation = useNavigation()

  const persisted = usePersisted({
    schema: ({ object }) =>
      object({
        workspaces: WorkspaceDataModel.array().default(() => []),
      }),
    methods: [{ type: 'local-storage', key: 'store/workspaces' }],
  })

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
    return persisted.workspaces.find((current) => current.name === name) ?? null
  }

  function del(name: string) {
    persisted.workspaces = persisted.workspaces.filter((current) => current.name !== name)
  }

  function create(name?: string | null) {
    name = getUniqueName(name)
    let workspace = get(name)
    if (workspace == null) {
      workspace = WorkspaceDataModel.parse({
        name,
        layout: [
          { height: 250, widgets: [{ type: 'messages' }] },
          { height: 250, widgets: [{ type: 'alerts' }] },
          { height: 250, widgets: [{ type: 'logs' }] },
          { height: 150, widgets: [{ type: 'procedures' }] },
        ],
      } as Zod.input<typeof WorkspaceDataModel>)

      persisted.workspaces = [...persisted.workspaces, workspace].sort((left, right) =>
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

  function copy(name: string, newName?: string | null) {
    const workspace = get(name)
    if (workspace == null) {
      return null
    }

    const copied = { ...workspace, name: getUniqueName(newName ?? name) }
    persisted.workspaces = [...persisted.workspaces, copied]
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
    all: computed(() => persisted.workspaces),
    get: getter(
      computed(() => persisted.workspaces),
      get
    ),
    create: getter(
      computed(() => persisted.workspaces),
      create
    ),
    rename,
    delete: del,
    copy,
    open,
  }
})
