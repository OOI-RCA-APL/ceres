<script lang="ts" setup>
import { until, useMediaQuery, useResizeObserver } from '@vueuse/core'
import { upperFirst } from 'lodash-es'
import { computed, watch } from 'vue'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useQuery } from '@/api/client'
import type { ConnectionInfo, ConnectionStateInfo, JobInfo, ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import type { ComponentAccessLevel } from '@/api/permissions'
import type { Connectivity } from '@/api/shared'
import CComponentWorkspaceStrip, {
  overviewFillHeight,
} from '@/components/c-component-workspace-strip.vue'
import { appHeaderHeight, pageHeaderHeight } from '@/components/c-full-page.vue'
import CWorkspace from '@/components/c-workspace.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { usePageParameter, useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { peekAt, useScrollMemory } from '@/scroll'
import { resolveTabs, useLastWorkspace, useRequestedWorkspaces, useTabs } from '@/tabs'
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
const navigation = useNavigation()
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

// The tab strip pins under this page's own header so scrolling the overview away leaves the
// component named above and its tabs directly beneath.
const workspaceStickyTop = appHeaderHeight + pageHeaderHeight

// Below this width the overview's two columns stack into one, which makes it roughly twice as
// tall. A height dragged on a wide screen then clips it mid-item so there it sizes to its own
// content instead and the drag handle goes away with the drag.
const overviewColumnsMin = 720
const overviewStacks = useMediaQuery(`(max-width: ${overviewColumnsMin - 1}px)`)

// Persist each section's open state per component address. The page remounts on navigation
// between components so this re-reads for the new address. Declared up here because the scroll
// memory below reads the overview's own state as it starts.
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

async function openScoped(id: string) {
  await tabs.open(address.toString(), id)
  revealScoped(id)
}

// A copy belongs next to its original so the strip reads as the original followed by its copy.
async function openBesideScoped(afterId: string, id: string) {
  await refreshScoped()
  await tabs.openBeside(
    address.toString(),
    id,
    afterId,
    scopedWorkspaces.map((workspace) => workspace.id),
  )
  revealScoped(id)
}

const lastWorkspace = useLastWorkspace(() => address.toString())

// Held here rather than read from the address. The address asks for a workspace and is cleared
// once it has been given one so what is showing is this page's own state from then on. Without a
// request the page falls back to whichever workspace was last shown here so a component with
// workspaces opens on one rather than on a bare overview.
let activeWorkspaceId = $ref<string | null>(null)

// What the address is currently asking for, which the fallback below waits for rather than
// choosing a workspace that is about to be replaced.
const requested = useRequestedWorkspaces(navigation.router)
const requestedIds = $computed(() => requested.workspace)

let overviewElement = $ref<HTMLElement | null>(null)

// Unsized, the overview reaches to where the strip rests on the bottom edge. Dragged, it is that
// height exactly, so shortening it takes effect rather than being floored back to the fill.
const overviewHeightStyle = $computed(() => ({
  height:
    persisted.overviewSize != null
      ? `${persisted.overviewSize}px`
      : overviewFillHeight(workspaceStickyTop),
}))

// What a drag starts from while the overview is still unsized, read off the box rather than
// recomputed, so the first move carries on from the height already on screen.
let overviewMeasuredHeight = $ref(0)
useResizeObserver($$(overviewElement), ([entry]) => {
  if (entry != null) {
    overviewMeasuredHeight = entry.contentRect.height
  }
})

// Zero until the box has been measured, and the handle waits for a real size rather than mounting
// on that and storing the minimum it clamps up to.
const overviewDragSize = $computed(() => persisted.overviewSize ?? overviewMeasuredHeight)

/** How far the page must be scrolled for the tab strip to have pinned under the header.

Measured from the overview, which sits above the strip and is never itself pinned, so its box is
reliable. The strip's own box stops moving once it pins. With no overview showing, the strip is at
the top from the start and there is nothing to scroll past.
*/
function pinnedAt(): number {
  if (persisted.overviewCollapsed || overviewElement == null) {
    return 0
  }

  const bottom = overviewElement.getBoundingClientRect().bottom + window.scrollY
  return Math.max(0, bottom - workspaceStickyTop)
}

/** Whether moving the page on a tab switch would be welcome.

With the overview showing and the page still above the pin, the overview is what is being read, so
jumping to wherever another workspace was left moves all of that out from under. Past the pin the
overview is out of view and the page is the workspace, which is when returning to where it was
left is the helpful thing.
*/
function isScrollSettled(): boolean {
  return window.scrollY >= pinnedAt()
}

// Switching tabs returns to where each workspace was left, the way switching browser tabs does,
// and never above the pin so a strip that was stuck to the header stays exactly where it was
// rather than dropping back down the page.
useScrollMemory(
  () => (activeWorkspaceId == null ? null : `${address.toString()}/${activeWorkspaceId}`),
  isScrollSettled,
  pinnedAt,
)

// Whatever is showing is what this component reopens on so it is recorded here rather than at
// each of the places that can choose one.
function showWorkspace(id: string) {
  activeWorkspaceId = id
  lastWorkspace.id = id
}

// Followed reactively so the floating action bar can yield while the strip rests at the
// bottom edge.
let stripRef = $ref<InstanceType<typeof CComponentWorkspaceStrip> | null>(null)
const stripDocked = $computed(() => stripRef?.docked ?? false)

// Reached to land a chart built from the particles section directly on the open workspace's
// live working copy.
let workspaceRef = $ref<InstanceType<typeof CWorkspace> | null>(null)

/** Show a workspace the user explicitly chose, bringing hidden content back and scrolling to
it when the strip is stuck at the bottom edge. The fallback selections after a close keep to
`showWorkspace` so a context menu action or a drag never unhides anything. */
function revealScoped(id: string) {
  persisted.workspaceCollapsed = false
  showWorkspace(id)
  if (stripRef == null) {
    return
  }

  // Resting at the bottom edge, the workspace is still below the fold and a peek is enough to
  // show it has opened. Anywhere else the strip is already up the page and the choice is a
  // request to see the workspace itself.
  const target = stripRef.docked ? peekAt(workspaceTop(), pinnedAt()) : pinnedAt()
  if (window.scrollY < target) {
    void stripRef.scrollTo(target)
  }
}

/** Show a workspace picked from the list, bringing the page down to it.

Only ever downwards. Past the pin the workspace is already what fills the screen, and scrolling
back to the pin from there would carry off whatever the user had scrolled to.
*/
/** Where the workspace starts, which is directly under the strip.

Derived from the overview rather than read off the strip, whose own box stops describing its
place in the page the moment it sticks to either edge.
*/
function workspaceTop(): number {
  if (overviewElement == null) {
    return 0
  }

  const bottom = overviewElement.getBoundingClientRect().bottom + window.scrollY
  return bottom + (stripRef?.element?.getBoundingClientRect().height ?? 0)
}

function openListed(id: string) {
  persisted.workspaceCollapsed = false
  showWorkspace(id)
  if (!isScrollSettled()) {
    void stripRef?.scrollTo(peekAt(workspaceTop(), pinnedAt()))
  }
}

/** Give the address what it asked for, then take the request back out of it.

Workspaces named there join this component's strip if they were not already on it so a link
behaves the same as opening them from the strip itself, and the first of them is what ends up
showing.

Only a workspace placed here can join because the strip resolves against this component's own
list and would drop anything else. Nothing is done until that list has landed since a link can
arrive before it does.
*/
async function adoptRequested() {
  if (requestedIds.length === 0) {
    return
  }

  const placed = new Set(placedWorkspaces.map((workspace) => workspace.id))
  const opening = requestedIds.filter((id) => placed.has(id))
  if (opening.length === 0 && placedWorkspaces.length === 0) {
    return
  }

  // Only this page's own request is taken back out, leaving whatever else the bar carries.
  requested.workspace = []
  if (opening.length === 0) {
    return
  }

  await tabs.openMany(address.toString(), opening)
  showWorkspace(opening[0] as string)
}

function shareScoped(ids: string[]) {
  void workspaces.copyLink(address.toString(), ids)
}

async function refreshScoped() {
  placedWorkspaces = inStandardOrder(await workspaces.listScoped(address))
}

// Dragging positions this user's own tabs. The shared standard order lives in `data.meta.order`
// and is edited from the overview so one user arranging their strip does not rearrange everyone
// else's.
async function reorderScoped(ordered: Workspace[]) {
  await tabs.reorder(
    address.toString(),
    ordered.map((workspace) => workspace.id),
  )
}

// Closing moves to whichever tab takes the closed one's place, or to the bare overview when it
// was the last one. The workspace itself is untouched, which separates closing from deleting.
async function closeScoped(id: string) {
  const remaining = scopedWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(address.toString(), id)

  if (activeWorkspaceId !== id) {
    return
  }

  activeWorkspaceId = remaining.length > 0 ? (remaining[0]?.id ?? null) : null
  if (activeWorkspaceId != null) {
    lastWorkspace.id = activeWorkspaceId
  }
}

// Closing the rest leaves the kept one showing, whether or not it was the one being looked at.
async function closeOtherScoped(id: string) {
  const others = scopedWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.closeMany(
    address.toString(),
    others.map((workspace) => workspace.id),
  )
  showWorkspace(id)
}

// Closing everything leaves the bare overview, which is where a component with no tabs sits.
async function closeAllScoped() {
  await tabs.closeMany(
    address.toString(),
    scopedWorkspaces.map((workspace) => workspace.id),
  )
  activeWorkspaceId = null
}

// Opening the rest keeps whatever was already showing since opening tabs is not a request to look
// somewhere else. With nothing showing it lands on the first of them.
async function openAllScoped() {
  const opening = openableWorkspaces.map((workspace) => workspace.id)
  await tabs.openMany(address.toString(), opening)

  if (activeWorkspaceId == null && opening.length > 0) {
    showWorkspace(opening[0] as string)
  }
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

// Watched rather than read once because this page stays mounted while a request arrives as a
// change of address rather than as a fresh visit.
watch(
  () => [requestedIds, placedWorkspaces] as const,
  () => {
    void adoptRequested()
  },
  { immediate: true },
)

// With nothing showing, the page opens on whichever workspace it last showed, falling back to the
// first tab when that one is gone. An empty strip leaves the bare overview, which is where a
// component with no tabs sits, and a request still pending is about to name one itself.
watch(
  () => [activeWorkspaceId, scopedWorkspaces, requestedIds] as const,
  ([active, listed, requested]) => {
    if (active != null || listed.length === 0 || requested.length > 0) {
      return
    }

    const remembered = listed.find((workspace) => workspace.id === lastWorkspace.id)
    showWorkspace((remembered ?? (listed[0] as Workspace)).id)
  },
  { immediate: true },
)

function createScoped() {
  dialogs.createWorkspace(address.toString()).onOk(async (created: Workspace) => {
    await refreshScoped()
    revealScoped(created.id)
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
  if (activeWorkspaceId != null && persisted.workspaceCollapsed) {
    persisted.workspaceCollapsed = false
    await until(() => workspaceRef != null).toBeTruthy({ timeout: 5000 })
  }

  // A missing page ref with a workspace open means it failed to mount, and falling through would
  // quietly create a second workspace for widgets meant for the open one.
  if (activeWorkspaceId != null) {
    if (workspaceRef == null) {
      notify.error('Failed to add the widgets to the open workspace.')
      return
    }

    // The first insert opens a fresh top row and the rest join it beside each other.
    workspaceRef.insertWidget(first, -1)
    for (const [index, widget] of rest.entries()) {
      workspaceRef.insertWidget(widget, 0, index + 1)
    }

    await workspaceRef.revealWidgets(widgets.map((widget) => widget.id))
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
    revealScoped(created.id)
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
    revealScoped((imported[0] as Workspace).id)
  }
}

await tabs.load()
await refreshScoped()

const queries = $computed(
  () => component?.procedures.filter((procedure) => procedure.type === 'query') ?? [],
)

const actions = $computed(
  () => component?.procedures.filter((procedure) => procedure.type === 'action') ?? [],
)

// Each procedure declares its own minimum level, listed here as reference rather than as a
// control since procedures are invoked from workspaces and interfaces instead of this page.
function permissionsLabel(procedure: ProcedureInfo): string {
  if (procedure.permissions === 'public') {
    return 'Public, requires no permissions.'
  }

  return `Requires "${procedure.permissions}" access permission.`
}

const permissionRank: Record<Exclude<ProcedureInfo['permissions'], 'public'>, number> = {
  view: 0,
  operate: 1,
  manage: 2,
  deny: 3,
}

// Whether the current user's access level meets the procedure's declared minimum.
function canInvoke(procedure: ProcedureInfo): boolean {
  if (procedure.permissions === 'public') {
    return true
  }

  const level: ComponentAccessLevel | null = effectiveAccess
  if (level == null) {
    return false
  }

  return permissionRank[level] >= permissionRank[procedure.permissions]
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

const connectivityColors: Record<Connectivity, string> = {
  connected: 'bg-success',
  connecting: 'bg-warning',
  disconnected: 'bg-error',
}

const running = $computed(() => engine.statuses.get(address)?.running ?? false)

// A stopped component's connections are expectedly down, shown inert grey rather than alarming
// red, with the pulse stilled to match.
function connectivityColor(connectivity: Connectivity): string {
  return running ? connectivityColors[connectivity] : 'bg-inverted/40'
}

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
    <template v-else>
      <div v-if="!persisted.overviewCollapsed" ref="overviewElement" class="relative">
        <!-- The dragged height only applies while workspace content shows below, and never less
        than what puts the strip at the bottom edge, where it rests until the page is scrolled.
        With workspace content hidden the overview is the page and takes its full height. -->
        <div
          class="max-h-[calc(100vh-92px)] overflow-x-hidden overflow-y-auto"
          :style="
            activeWorkspaceId != null && !persisted.workspaceCollapsed && !overviewStacks
              ? overviewHeightStyle
              : undefined
          "
        >
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
                @close="closeScoped"
                @open="openListed"
                @open-beside="openBesideScoped"
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
                @close="closeScoped"
                @open="openListed"
                @open-beside="openBesideScoped"
                @share="shareScoped"
              />

              <c-list>
                <c-detail-section
                  v-model:expanded="persisted.connections"
                  :title="`Connections (${connections.length})`"
                >
                  <c-text v-if="connections.length === 0" class="px-3" variant="description">
                    No connections.
                  </c-text>
                  <c-list-item v-for="connection in connections" :key="connection.name">
                    <div class="grow">
                      <div class="flex items-baseline gap-2">
                        <c-text variant="body3">{{ connection.name }}</c-text>
                        <c-text v-if="connection.label" variant="description">
                          {{ connection.label }}
                        </c-text>
                      </div>
                      <c-text variant="description">{{ connection.uri }}</c-text>
                    </div>
                    <c-tooltip
                      v-if="'connectivity' in connection"
                      :text="upperFirst(connection.connectivity)"
                    >
                      <span
                        :class="[
                          $style.dot,
                          !running && $style.still,
                          connectivityColor(connection.connectivity),
                        ]"
                      />
                    </c-tooltip>
                  </c-list-item>
                </c-detail-section>
                <c-detail-section
                  v-model:expanded="persisted.jobs"
                  :title="`Jobs (${jobs.length})`"
                >
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
                      <c-text variant="description">{{ permissionsLabel(query) }}</c-text>
                    </div>
                    <c-badge v-if="query.live" color="success" size="sm" variant="subtle">
                      live
                    </c-badge>
                    <c-tooltip v-if="!canInvoke(query)" text="Not available with your access.">
                      <c-icon class="size-4 text-muted" :name="icons.locked" />
                    </c-tooltip>
                  </c-list-item>
                </c-detail-section>
                <c-detail-section
                  v-model:expanded="persisted.actions"
                  :title="`Actions (${actions.length})`"
                >
                  <c-text v-if="actions.length === 0" class="px-3" variant="description">
                    No actions.
                  </c-text>
                  <c-list-item v-for="action in actions" :key="action.name">
                    <div class="grow">
                      <c-text variant="body3">{{ action.name }}</c-text>
                      <c-text variant="description">{{ permissionsLabel(action) }}</c-text>
                    </div>
                    <c-tooltip v-if="!canInvoke(action)" text="Not available with your access.">
                      <c-icon class="size-4 text-muted" :name="icons.locked" />
                    </c-tooltip>
                  </c-list-item>
                </c-detail-section>
              </c-list>

              <c-component-particles-section
                v-model:expanded="persisted.particles"
                v-model:expanded-types="persisted.particleTypes"
                :address
                class="mt-2"
                :insert-at="workspaceRef?.insertWidgetsAt"
                :insert-drag="workspaceRef?.startInsertDrag"
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
        </div>
        <c-resize-handle
          v-if="activeWorkspaceId != null && !persisted.workspaceCollapsed && !overviewStacks"
          class="absolute bottom-0 left-0"
          direction="vertical"
          :max="800"
          :min="120"
          :model-value="overviewDragSize"
          @update:model-value="(value: number) => (persisted.overviewSize = value)"
        />
      </div>
      <!-- The strip sits in flow between the overview and the workspace, and sticks at both edges
      so it is always on screen, pinning under the header the way it always has and resting at the
      bottom while its own place is still below the fold. -->
      <c-component-workspace-strip
        v-if="scopedWorkspaces.length > 0 || canCreate"
        ref="stripRef"
        v-model:collapsed="persisted.workspaceCollapsed"
        :sticky-top="workspaceStickyTop"
      >
        <template #default="{ docked, trailingInset }">
          <c-component-workspace-tabs
            :active="activeWorkspaceId"
            :active-actions="workspaceRef?.headerActions"
            :active-state="workspaceRef?.headerState"
            bound
            :can-create="canCreate"
            :can-manage="canManage"
            :docked="docked"
            :openable="openableWorkspaces"
            :trailing-inset="trailingInset"
            :workspaces="scopedWorkspaces"
            @close="closeScoped"
            @close-all="closeAllScoped"
            @close-others="closeOtherScoped"
            @create="createScoped"
            @import="importScoped"
            @open="openScoped"
            @open-all="openAllScoped"
            @open-beside="openBesideScoped"
            @reorder="reorderScoped"
            @select="revealScoped"
            @share="shareScoped"
          />
        </template>
      </c-component-workspace-strip>
      <!-- Deliberately not keyed on the workspace ID, so switching tabs updates this page in
      place. -->
      <c-workspace
        v-if="activeWorkspaceId != null && !persisted.workspaceCollapsed"
        :id="activeWorkspaceId"
        ref="workspaceRef"
        :sticky-top="workspaceStickyTop"
        :strip-docked="stripDocked"
        @duplicated="openBesideScoped"
      />
    </template>
  </c-full-page>
</template>

<style module>
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

.still {
  animation: none;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.65;
  }
}
</style>
