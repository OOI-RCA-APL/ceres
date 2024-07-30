import { AddressModel } from '@/api/address'
import { getter } from '@/getter'
import { useNavigation } from '@/navigation'
import { usePersisted } from '@/persistence'
import { workspaceContextInjectionKey } from '@/symbols'
import { defineStore } from 'pinia'
import { v4 } from 'uuid'
import { computed, inject, MaybeRef, provide, reactive, unref } from 'vue'
import Zod from 'zod'

export type BaseWidget = Zod.infer<typeof BaseWidgetModel>
const BaseWidgetModel = Zod.object({
  id: Zod.string().default(() => v4()),
  width: Zod.number().default(100),
})

export type MessagesWidget = Zod.infer<typeof MessagesWidgetModel>
export const MessagesWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('messages'),
})

export type AlertsWidget = Zod.infer<typeof AlertsWidgetModel>
export const AlertsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('alerts'),
})

export type LogsWidget = Zod.infer<typeof LogsWidgetModel>
export const LogsWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('logs'),
})

export type ProceduresWidget = Zod.infer<typeof ProceduresWidgetModel>
export const ProceduresWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('procedures'),
})

export type UIWidget = Zod.infer<typeof UIWidgetModel>
export const UIWidgetModel = BaseWidgetModel.extend({
  type: Zod.literal('ui'),
  address: AddressModel,
})

export type Widget = Zod.infer<typeof WidgetModel>
export const WidgetModel = Zod.discriminatedUnion('type', [
  MessagesWidgetModel,
  AlertsWidgetModel,
  LogsWidgetModel,
  ProceduresWidgetModel,
  UIWidgetModel,
])

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

function createWorkspaceContext(options: WorkspaceContextOptions) {
  const workspaces = useWorkspaces()

  function create() {
    return workspaces.create(unref(options.name))
  }

  function rename(newName: string) {
    return workspaces.rename(unref(options.name), newName)
  }

  function copy(newName?: string | null) {
    return workspaces.copy(unref(options.name), newName)
  }

  function del() {
    workspaces.delete(unref(options.name))
  }

  return reactive({
    name: computed(() => unref(options.name)),
    workspace: computed(() => workspaces.get(unref(options.name))),
    create,
    copy,
    delete: del,
    rename,
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
    schema: ({ object, array }) =>
      object({
        workspaces: array(WorkspaceDataModel).default(() => []),
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
