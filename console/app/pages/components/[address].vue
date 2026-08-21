<script lang="ts" setup>
import { until, useMediaQuery } from '@vueuse/core'
import { upperFirst } from 'lodash-es'
import { computed, watch } from 'vue'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useQuery } from '@/api/client'
import type {
  ActionInfo,
  ConnectionInfo,
  ConnectionStateInfo,
  JobInfo,
  ProcedureInfo,
} from '@/api/components'
import { canInvokeProcedure, describeProcedurePermissions } from '@/api/components'
import { useEngine } from '@/api/engine'
import type { ComponentAccessLevel } from '@/api/permissions'
import CWorkspaceHost from '@/components/c-workspace-host.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { usePageParameter } from '@/navigation'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { resolveTabs, useTabs } from '@/tabs'
import { utc } from '@/time'
import { highlight } from '@/utilities'
import {
  inStandardOrder,
  openedRowFor,
  type Widget,
  type Workspace,
  useWorkspaces,
} from '@/workspace'

definePageMeta({ auth: true })

const engine = useEngine()
const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const notify = useNotify()
const tabs = useTabs()
const workspaces = useWorkspaces()

const address = Address.parse(usePageParameter('address'))

const component = $computed(() => engine.components.get(address))

const effectiveAccess = $computed<ComponentAccessLevel | null>(() =>
  access.levelFor(address.toString()),
)

const canManage = $computed(() => access.canManage(address.toString()))

// Adding a workspace here needs only view because a user without manage gets a private one,
// which nobody else sees.
const canCreate = $computed(() => access.canView(address.toString()))

// Below this width the overview's two columns stack into one, which makes it roughly twice as
// tall. A height dragged on a wide screen then clips it mid-item so there it sizes to its own
// content instead and the drag handle goes away with the drag.
const overviewColumnsMin = 720
const overviewStacks = useMediaQuery(`(max-width: ${overviewColumnsMin - 1}px)`)

// Persist each section's open state per component address. The page remounts on navigation
// between components so this re-reads for the new address.
const persisted = usePersisted({
  schema: ({ object, boolean, number, record, string }) =>
    object({
      configuration: boolean().default(true),
      workspaces: boolean().default(true),
      connections: boolean().default(false),
      jobs: boolean().default(false),
      particles: boolean().default(false),
      particleTypes: record(string(), boolean()).default({}),
      queries: boolean().default(false),
      actions: boolean().default(false),
      overviewCollapsed: boolean().default(false),
      overviewSize: number().nullable().default(null),
      workspaceCollapsed: boolean().default(false),
    }),
  methods: computed(() => [
    { type: 'local-storage' as const, key: ['component-detail-drawers', address] },
  ]),
})

// A collapsed configuration leaves its column as one closed bar with the rest of the panel empty
// beside it so the workspaces move under it and the reference lists get the width to themselves.
// Stacked there is only one column, and expanded the configuration fills its own.
const workspacesUnderConfig = $computed(
  () => configHighlighted != null && !overviewStacks.value && !persisted.configuration,
)

// The shared default set for this component, in standard order.
let placedWorkspaces = $ref<Workspace[]>([])

// What this user's strip actually shows. The defaults are what someone who has never touched this
// strip sees, and their own set takes over from there.
const scopedWorkspaces = $computed(() =>
  resolveTabs(placedWorkspaces, tabs.setFor(address.toString()), (workspace) => workspace.id),
)

// Placed here but not in the strip, which the add button offers before creating one.
const openableWorkspaces = $computed(() => {
  const shown = new Set(scopedWorkspaces.map((workspace) => workspace.id))
  return placedWorkspaces.filter((workspace) => !shown.has(workspace.id))
})

let hostRef = $ref<InstanceType<typeof CWorkspaceHost> | null>(null)

function shareScoped(ids: string[]) {
  void workspaces.copyLink(address.toString(), ids)
}

async function refreshScoped() {
  placedWorkspaces = inStandardOrder(await workspaces.listScoped(address))
}

// Scoped workspaces are fetched separately from the store's own list so the tabs are refetched
// whenever that list changes. The store refreshes it after every create, update, and delete,
// which covers a workspace being renamed or deleted from the tab shown below.
watch(
  () => workspaces.all,
  () => {
    void refreshScoped()
  },
)

function createScoped() {
  dialogs.createWorkspace(address.toString()).onOk(async (created: Workspace) => {
    await refreshScoped()
    hostRef?.reveal(created.id)
  })
}

/** Land widgets the particles section built on the workspace open on this component's strip,
through its live editing session so they show immediately as uncommitted changes. With none
open, a private workspace is created and opened to carry them. */
async function createWidgetsScoped(widgets: Widget[]) {
  const [first, ...rest] = widgets
  if (first == null) {
    return
  }

  // Hidden workspace content comes back first, since the widgets land through the mounted page.
  if (hostRef?.activeWorkspaceId != null && persisted.workspaceCollapsed) {
    persisted.workspaceCollapsed = false
    await until(() => hostRef?.workspace != null).toBeTruthy({ timeout: 5000 })
  }

  // A missing workspace ref with one open means it failed to mount, and falling through would
  // quietly create a second workspace for widgets meant for the open one.
  if (hostRef?.activeWorkspaceId != null) {
    const open = hostRef.workspace
    if (open == null) {
      notify.error('Failed to add the widgets to the open workspace.')
      return
    }

    // The first insert opens a fresh top row and the rest join it beside each other.
    open.insertWidget(first, -1)
    for (const [index, widget] of rest.entries()) {
      open.insertWidget(widget, 0, index + 1)
    }

    await open.revealWidgets(widgets.map((widget) => widget.id))
    return
  }

  try {
    const created = await workspaces.create({
      scope: address.toString(),
      owner_id: auth.user?.id,
      data: {
        layout: [openedRowFor(widgets)],
        meta: {},
      },
    })
    await refreshScoped()
    hostRef?.reveal(created.id)
  } catch {
    notify.error('Failed to add the widgets.')
  }
}

// A file dropped on this component's strip belongs to this component, and is shared or private on
// the same terms as one created here.
async function importScoped(files: File[]) {
  const imported = await workspaces.importWorkspaces(files, {
    scope: address,
    owner_id: canManage ? null : auth.user?.id,
  })
  await refreshScoped()
  if (imported.length > 0) {
    hostRef?.reveal((imported[0] as Workspace).id)
  }
}

await tabs.load()
await refreshScoped()

const queries = $computed(
  () => component?.procedures.filter((procedure) => procedure.type === 'query') ?? [],
)

const actions = $computed(
  () =>
    component?.procedures.filter(
      (procedure): procedure is ActionInfo => procedure.type === 'action',
    ) ?? [],
)

function canInvoke(procedure: ProcedureInfo): boolean {
  return canInvokeProcedure(procedure, effectiveAccess)
}

const accessIcon = $computed(() => {
  const level: ComponentAccessLevel | null = effectiveAccess
  return level == null ? icons.locked : icons[level]
})

// The endpoint rejects callers with no access to the component, in which case the failure is
// expected and simply hides the section.
const configQuery = useQuery({
  queryKey: computed(() => ['component-config', address.toString()]),
  queryFn: () => engine.components.getConfig(address),
  retry: false,
})

const jobsQuery = useQuery({
  queryKey: computed(() => ['component-jobs', address.toString()]),
  queryFn: () => engine.components.getJobs(address),
  retry: false,
})

const connectionsQuery = useQuery({
  queryKey: computed(() => ['component-connections', address.toString()]),
  queryFn: () => engine.components.getConnections(address),
  retry: false,
})

// The statuses stream pushes on lifecycle and connectivity events so a refetch on each push keeps
// connection states and job schedules current without polling. Jobs are included because a
// component's scheduler stops and starts with it, changing each job's next run time.
watch(
  () => engine.statuses.get(address),
  () => {
    void connectionsQuery.refetch()
    void jobsQuery.refetch()
  },
)

const connections = $computed<(ConnectionInfo | ConnectionStateInfo)[]>(
  () => connectionsQuery.data.value ?? component?.connections ?? [],
)

const running = $computed(() => engine.statuses.get(address)?.running ?? false)

const jobs = $computed(() => jobsQuery.data.value ?? [])

/** Describe a job's schedule and expected next run for display beneath its name. */
function jobLabel(job: JobInfo): string {
  const schedule = `Schedule "${job.schedule}"`
  if (job.next_run == null) {
    return `${schedule}, not scheduled to run.`
  }

  return `${schedule}, next run at ${utc(job.next_run).format('YYYY-MM-DD HH:mm')} UTC.`
}

const configText = $computed(() => {
  const config = configQuery.data.value
  if (config == null) {
    return null
  }

  // Shown as YAML to match how the configuration is written in `ceres.yaml`.
  return stringify(config)
})

const configHighlighted = $computed(() =>
  configText == null ? null : highlight(configText, 'yaml'),
)
</script>

<template>
  <c-full-page fill :title="component?.address?.toString() ?? address.toString()">
    <template #header-append>
      <c-status-badge v-if="component" :address class="ml-2" :scale="0.65" />
      <div class="flex-1" />
      <c-tooltip :text="`${persisted.overviewCollapsed ? 'Show' : 'Hide'} Details`">
        <c-button
          class="mr-2"
          :color="persisted.overviewCollapsed ? 'neutral' : 'primary'"
          :icon="persisted.overviewCollapsed ? icons.menuDown : icons.menuUp"
          size="xs"
          :trailing-icon="icons.overview"
          variant="ghost"
          @click="persisted.overviewCollapsed = !persisted.overviewCollapsed"
        />
      </c-tooltip>
      <!-- Flush with the right edge of the widgets below, whose cards sit half a gutter in. -->
      <c-tooltip
        v-if="effectiveAccess != null"
        :text="`You have permissions to ${effectiveAccess} this component.`"
      >
        <c-badge class="mr-2" color="primary" :icon="accessIcon" size="sm">
          {{ upperFirst(effectiveAccess) }}
        </c-badge>
      </c-tooltip>
    </template>

    <div v-if="component == null" class="p-12 text-center text-muted">Component not found.</div>
    <c-workspace-host
      v-else
      ref="hostRef"
      v-model:overview-collapsed="persisted.overviewCollapsed"
      v-model:overview-size="persisted.overviewSize"
      v-model:workspace-collapsed="persisted.workspaceCollapsed"
      :adoptable="placedWorkspaces"
      bound
      :can-create="canCreate"
      :can-manage="canManage"
      :openable="openableWorkspaces"
      :placement="address.toString()"
      :refresh="refreshScoped"
      :resizable="!overviewStacks"
      :workspaces="scopedWorkspaces"
      @create="createScoped"
      @import="importScoped"
      @share="shareScoped"
    >
      <template #overview="{ openListed }">
        <div class="grid min-h-full grid-cols-12 gap-4 p-4">
          <div
            v-if="configHighlighted != null"
            class="col-span-12 min-h-0 min-[720px]:col-span-5"
            :class="persisted.configuration && 'flex flex-col'"
          >
            <div class="border-default flex min-h-0 flex-col rounded-md border">
              <c-detail-section v-model:expanded="persisted.configuration" title="Configuration">
                <!-- eslint-disable vue/no-v-html -->
                <!-- prettier-ignore -->
                <pre
                  class="m-0 overflow-x-auto px-3 pb-3 text-[12px] leading-normal"
                ><code v-html="configHighlighted" /></pre>
                <!-- eslint-enable vue/no-v-html -->
              </c-detail-section>
            </div>
            <c-component-workspaces-section
              v-if="workspacesUnderConfig"
              v-model:expanded="persisted.workspaces"
              :can-manage="canManage"
              class="mt-2"
              collapsible
              :open-ids="scopedWorkspaces.map((workspace) => workspace.id)"
              :placement="address.toString()"
              :workspaces="placedWorkspaces"
              @close="(id: string) => hostRef?.close(id)"
              @open="openListed"
              @open-beside="(afterId: string, id: string) => hostRef?.openBeside(afterId, id)"
              @share="shareScoped"
            />
          </div>

          <div
            :class="
              configHighlighted != null ? 'col-span-12 min-[720px]:col-span-7' : 'col-span-12'
            "
          >
            <!-- Workspaces lead the column rather than sitting under the procedure lists, since
            they are what the page is usually opened for and the rest is reference. -->
            <c-component-workspaces-section
              v-if="!workspacesUnderConfig"
              v-model:expanded="persisted.workspaces"
              :can-manage="canManage"
              class="mb-2"
              collapsible
              :open-ids="scopedWorkspaces.map((workspace) => workspace.id)"
              :placement="address.toString()"
              :workspaces="placedWorkspaces"
              @close="(id: string) => hostRef?.close(id)"
              @open="openListed"
              @open-beside="(afterId: string, id: string) => hostRef?.openBeside(afterId, id)"
              @share="shareScoped"
            />

            <c-list>
              <c-component-connections-section
                v-model:expanded="persisted.connections"
                :address
                :connections
                :insert-at="hostRef?.workspace?.insertWidgetsAt"
                :insert-drag="hostRef?.workspace?.startInsertDrag"
                :running
                @create="createWidgetsScoped"
              />
              <c-detail-section v-model:expanded="persisted.jobs" :title="`Jobs (${jobs.length})`">
                <c-text v-if="jobs.length === 0" class="px-3" variant="description">
                  No jobs.
                </c-text>
                <c-list-item v-for="job in jobs" :key="job.name">
                  <div class="grow">
                    <c-text variant="body3">{{ job.name }}</c-text>
                    <c-text variant="description">{{ jobLabel(job) }}</c-text>
                  </div>
                </c-list-item>
              </c-detail-section>
            </c-list>

            <c-list class="mt-2">
              <c-detail-section
                v-model:expanded="persisted.queries"
                :title="`Queries (${queries.length})`"
              >
                <c-text v-if="queries.length === 0" class="px-3" variant="description">
                  No queries.
                </c-text>
                <c-list-item v-for="query in queries" :key="query.name">
                  <div class="grow">
                    <c-text variant="body3">{{ query.name }}</c-text>
                    <c-text variant="description">
                      {{ describeProcedurePermissions(query) }}
                    </c-text>
                  </div>
                  <c-badge v-if="query.live" color="success" size="sm" variant="subtle">
                    live
                  </c-badge>
                  <c-tooltip v-if="!canInvoke(query)" text="Not available with your access.">
                    <c-icon class="size-4 text-muted" :name="icons.locked" />
                  </c-tooltip>
                </c-list-item>
              </c-detail-section>
              <c-component-actions-section
                v-model:expanded="persisted.actions"
                :access="effectiveAccess"
                :actions
                :address
                :insert-at="hostRef?.workspace?.insertWidgetsAt"
                :insert-drag="hostRef?.workspace?.startInsertDrag"
                @create="createWidgetsScoped"
              />
            </c-list>

            <c-component-particles-section
              v-model:expanded="persisted.particles"
              v-model:expanded-types="persisted.particleTypes"
              :address
              class="mt-2"
              :insert-at="hostRef?.workspace?.insertWidgetsAt"
              :insert-drag="hostRef?.workspace?.startInsertDrag"
              @create="createWidgetsScoped"
            />

            <div v-if="component.tags.length > 0" class="mt-2">
              <c-text class="mb-1" variant="th">Tags</c-text>
              <div class="flex flex-wrap gap-1">
                <c-badge
                  v-for="tag in component.tags"
                  :key="tag"
                  color="neutral"
                  size="sm"
                  variant="outline"
                >
                  {{ tag }}
                </c-badge>
              </div>
            </div>
          </div>

          <div v-if="component.components.length > 0" class="col-span-12">
            <c-text class="mb-1" variant="th">Subcomponents</c-text>
            <c-list>
              <c-list-item
                v-for="child in component.components"
                :key="child.name"
                :to="`/components/${child.address}`"
              >
                <div class="grow">
                  <c-text variant="body3">{{ child.name }}</c-text>
                  <c-text variant="description">{{ child.address }}</c-text>
                </div>
                <c-status-badge :address="child.address" />
              </c-list-item>
            </c-list>
          </div>
        </div>
      </template>
    </c-workspace-host>
  </c-full-page>
</template>
