import { useQuery } from '@tanstack/vue-query'
import { useEventListener } from '@vueuse/core'
import { debounce } from 'lodash-es'
import { defineStore } from 'pinia'
import { v7 } from 'uuid'
import {
  computed,
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

import { User, UserRoleOf } from './api/users'

import { AddressModel, AddressSelectorModel } from '@/api/address'
import { AlertFilterModel } from '@/api/alerts'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ProcedureTypeModel } from '@/api/components'
import { LogEntryFilterModel } from '@/api/logs'
import { MessageFilterModel } from '@/api/messages'
import { ParticleFilterModel } from '@/api/particles'
import { DateTimeModel } from '@/api/shared'
import { useNavigation } from '@/navigation'
import { workspaceInjectionKey } from '@/symbols'
import { deepClone, jsonEquals, safeArrayOf } from '@/utilities'

export type BaseWidget = Zod.infer<typeof BaseWidgetModel>
const BaseWidgetModel = Zod.object({
  id: Zod.string().catch(() => v7()),
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
  timespan: Zod.union([Zod.number(), Zod.string()])
    .nullish()
    .catch(60 * 60),
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
  id: Zod.string().catch(() => v7()),
  height: Zod.number().catch(250),
  collapsed: Zod.boolean().catch(false),
  widgets: safeArrayOf(WidgetModel),
})

export type WorkspaceDataInput = Zod.input<typeof WorkspaceDataModel>
export type WorkspaceData = Zod.infer<typeof WorkspaceDataModel>
export const WorkspaceDataModel = Zod.object({
  layout: WidgetRowModel.array().catch(() => []),
})

export type WorkspaceAccessRestriction = Zod.infer<typeof WorkspaceAccessRestrictionModel>
export const WorkspaceAccessRestrictionModel = Zod.enum([
  'anyone',
  'operators',
  'admins',
  'private',
])
export const WorkspaceAccessRestrictionOf = {
  anyone: 0,
  operators: 1,
  admins: 2,
  private: 3,
} as const

export type Workspace = Zod.infer<typeof WorkspaceModel>
export type WorkspaceInput = Zod.input<typeof WorkspaceModel>
export const WorkspaceModel = Zod.object({
  id: Zod.string().catch(() => v7()),
  name: Zod.string(),
  general_viewership: WorkspaceAccessRestrictionModel.default('private'),
  general_editorship: WorkspaceAccessRestrictionModel.default('private'),
  general_managership: WorkspaceAccessRestrictionModel.default('private'),
  data: WorkspaceDataModel.catch(() => WorkspaceDataModel.parse({})),
})

export type WorkspaceMembershipRole = Zod.infer<typeof WorkspaceMembershipRoleModel>
export const WorkspaceMembershipRoleModel = Zod.enum(['viewer', 'editor', 'manager'])

export const WorkspaceMembershipRoleOf = {
  viewer: 0,
  editor: 1,
  manager: 2,
} as const

export type WorkspaceMembership = Zod.infer<typeof WorkspaceMembershipModel>
export const WorkspaceMembershipModel = Zod.object({
  user_id: Zod.string(),
  workspace_id: Zod.string(),
  role: WorkspaceMembershipRoleModel.default('viewer'),
  data: WorkspaceDataModel.nullish().catch(null),
})

export type WorkspaceEdit = Zod.infer<typeof WorkspaceEditModel>
export const WorkspaceEditModel = Zod.object({
  user_id: Zod.string(),
  workspace_id: Zod.string(),
  data: WorkspaceDataModel,
})

export type WorkspaceContext = ReturnType<typeof createWorkspaceContext>

export type Drag = {
  widget: Widget
  row: number
  column: number
}

function createWorkspaceContext(workspaceId: MaybeRef<string>) {
  const auth = useAuth()
  const workspaces = useWorkspaces()
  const id = $computed(() => unref(workspaceId))

  const query = useQuery({
    queryKey: computed(() => ['workspace-context', id, auth.user?.id]),
    experimental_prefetchInRender: true,
    queryFn: async () => {
      return {
        workspace: await workspaces.get(id),
        membership: await workspaces.getMembership(id),
      }
    },
  })

  const workspace = $computed(
    () =>
      (query.data.value?.workspace
        ? readonly(query.data.value.workspace)
        : null) as Workspace | null
  )

  const membership = $computed(
    () => (query.data.value?.membership ?? null) as WorkspaceMembership | null
  )

  let data = $ref<WorkspaceData | null>(null)

  async function saveEdit() {
    if (workspace == null || data == null) {
      return
    }

    console.log(`Saving edit for workspace ${id}.`)
    await workspaces.assignEdit(id, data)
  }

  watch($$(data), debounce(saveEdit, 500), { deep: true })

  useEventListener(window, 'beforeunload', async () => {
    try {
      await saveEdit()
    } catch {
      // Ignore.
    }
  })

  const edited = $computed(
    () => data != null && workspace != null && !jsonEquals(data, workspace?.data)
  )

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

  async function join(role: WorkspaceMembershipRole) {
    const result = await workspaces.join(id, role)
    await refresh()
    return result
  }

  async function leave() {
    const result = await workspaces.leave(id)
    await refresh()
    return result
  }

  function insertWidget(widget: Widget, row: number, column: number = 0) {
    if (data == null) {
      return
    }

    row = Math.min(data.layout.length, row)
    const widgets = [...(data.layout[row]?.widgets ?? [])]
    widgets.splice(column, 0, widget)
    widget.width = Math.min(100 / widgets.length, widget.width)
    resolveWidgetWidths(widgets, widgets.indexOf(widget))

    if (row < 0) {
      data.layout = [WidgetRowModel.parse({ widgets }), ...data.layout]
    } else if (data.layout[row] == null) {
      data.layout = [...data.layout, WidgetRowModel.parse({ widgets })]
    } else {
      data.layout[row].widgets = widgets
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
    widget.width = Math.min(100 / destinationRow.widgets.length, widget.width)
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
    }
  }

  async function load() {
    await query.promise.value
    await afterFetch()
  }

  async function refresh() {
    await query.refetch()
    await workspaces.refresh()
    await afterFetch()
  }

  return reactive({
    load,
    refresh,
    name: computed(() => workspace?.name ?? null),
    membership: computed(() => membership),
    defaultViewership: computed(() => workspace?.general_viewership ?? 'private'),
    defaultEditorship: computed(() => workspace?.general_editorship ?? 'private'),
    defaultManagership: computed(() => workspace?.general_managership ?? 'private'),
    originalData: computed(() => workspace?.data ?? null),
    data: computed(() => data),
    edited: computed(() => edited),
    delete: del,
    rename,
    update,
    save,
    revert,
    join,
    leave,
    getWidget,
    getWidgetAt,
    getWidgetPosition,
    insertWidget,
    addWidget,
    deleteWidget,
    moveWidget,
    duplicateWidget,
    drag: null as Drag | null,
    canView: computed(() => workspace != null && userCanViewWorkspace(auth.user, membership)),
    couldView: computed(() => workspace != null && userCouldViewWorkspace(auth.user, workspace)),
    canEdit: computed(() => workspace != null && userCanEditWorkspace(auth.user, membership)),
    couldEdit: computed(() => workspace != null && userCouldEditWorkspace(auth.user, workspace)),
    canManage: computed(() => workspace != null && userCanManageWorkspace(auth.user, membership)),
    couldManage: computed(
      () => workspace != null && userCouldManageWorkspace(auth.user, workspace)
    ),
  })
}

export function provideWorkspace(id: string) {
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

  async function getAll() {
    return await client.get(`/api/workspaces`, {
      parse: Zod.array(WorkspaceModel),
      query: {
        'viewable-by': getUserId(),
      },
    })
  }

  async function getAllJoined() {
    return await client.get(`/api/users/${getUserId()}/workspaces`, {
      parse: Zod.array(WorkspaceModel),
    })
  }

  const query = useQuery({
    queryKey: computed(() => ['workspaces', auth.user?.id]),
    queryFn: async () => {
      const [all, joined, memberships] = await Promise.all([
        getAll(),
        getAllJoined(),
        getMemberships(),
      ])
      return { all, joined, memberships }
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

  const joinedWorkspaces = $computed(
    () => new Map((query.data.value?.joined ?? []).map((workspace) => [workspace.id, workspace]))
  )

  const unjoinedWorkspaces = $computed(
    () =>
      new Map(
        [...allWorkspaces.values()]
          .filter((workspace) => !joinedWorkspaces.has(workspace.id))
          .map((workspace) => [workspace.id, workspace])
      )
  )

  const memberships = $computed(
    () =>
      new Map(
        (query.data.value?.memberships ?? []).map((membership) => [
          membership.workspace_id,
          membership,
        ])
      )
  )

  async function create(
    workspace?: Omit<WorkspaceInput, 'name'> & { name?: string }
  ): Promise<Workspace> {
    workspace = WorkspaceModel.parse({ name: 'New Workspace', ...workspace })
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

  async function getMembership(workspaceId: string) {
    if (auth.user == null) {
      return null
    }

    try {
      return await client.get(`/api/users/${auth.user.id}/workspace-memberships/${workspaceId}`, {
        parse: WorkspaceMembershipModel,
      })
    } catch {
      return null
    }
  }

  function getStoredMembership(workspaceId: string) {
    return memberships.get(workspaceId)
  }

  async function getMemberships() {
    if (auth.user == null) {
      return []
    }

    return await client.get(`/api/users/${auth.user.id}/workspace-memberships`, {
      parse: Zod.array(WorkspaceMembershipModel),
    })
  }

  async function getMembershipsInWorkspace(workspaceId: string) {
    return await client.get(`/api/workspaces/${workspaceId}/memberships`, {
      parse: Zod.array(WorkspaceMembershipModel),
    })
  }

  async function createMembership(
    userId: string,
    workspaceId: string,
    role: WorkspaceMembershipRole
  ) {
    return await client.post(`/api/users/${userId}/workspace-memberships/${workspaceId}`, {
      data: {
        role,
      },
      parse: WorkspaceMembershipModel,
    })
  }

  async function updateMembership(
    userId: string,
    workspaceId: string,
    data: Partial<WorkspaceMembership>
  ) {
    return await client.patch(`/api/users/${userId}/workspace-memberships/${workspaceId}`, {
      data,
      parse: WorkspaceMembershipModel,
    })
  }

  async function deleteMembership(userId: string, workspaceId: string) {
    return await client.delete(`/api/users/${userId}/workspace-memberships/${workspaceId}`)
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

  async function join(workspaceId: string, role: WorkspaceMembershipRole) {
    return await createMembership(getUserId(), workspaceId, role)
  }

  async function leave(workspaceId: string) {
    return await deleteMembership(getUserId(), workspaceId)
  }

  return {
    load,
    refresh,
    all: computed(() => [...allWorkspaces.values()]),
    joined: computed(() => [...joinedWorkspaces.values()]),
    unjoined: computed(() => [...unjoinedWorkspaces.values()]),
    memberships: computed(() => [...memberships.values()]),
    get,
    getAll,
    getAllJoined,
    create,
    rename,
    update,
    open,
    delete: del,
    getMembership,
    getStoredMembership,
    getMemberships,
    getMembershipsInWorkspace,
    createMembership,
    updateMembership,
    deleteMembership,
    getEdit,
    assignEdit,
    discardEdit,
    join,
    leave,
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

export function userCouldViewWorkspace(user: User | null, workspace: Workspace) {
  return (
    user != null &&
    UserRoleOf[user.role] >= WorkspaceAccessRestrictionOf[workspace.general_viewership]
  )
}

export function userCanViewWorkspace(user: User | null, membership: WorkspaceMembership | null) {
  if (user == null) {
    return false
  }

  return (
    membership != null &&
    WorkspaceMembershipRoleOf[membership.role] >= WorkspaceMembershipRoleOf.viewer
  )
}

export function userCouldEditWorkspace(user: User | null, workspace: Workspace) {
  return (
    user != null &&
    UserRoleOf[user.role] >= WorkspaceAccessRestrictionOf[workspace.general_editorship]
  )
}

export function userCanEditWorkspace(user: User | null, membership: WorkspaceMembership | null) {
  if (user == null) {
    return false
  }

  return (
    membership != null &&
    WorkspaceMembershipRoleOf[membership.role] >= WorkspaceMembershipRoleOf.editor
  )
}

export function userCouldManageWorkspace(user: User | null, workspace: Workspace) {
  return (
    user != null &&
    UserRoleOf[user.role] >= WorkspaceAccessRestrictionOf[workspace.general_managership]
  )
}

export function userCanManageWorkspace(user: User | null, membership: WorkspaceMembership | null) {
  if (user == null) {
    return false
  }

  return (
    membership != null &&
    WorkspaceMembershipRoleOf[membership.role] >= WorkspaceMembershipRoleOf.manager
  )
}
