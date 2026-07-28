<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { upperFirst } from 'lodash-es'
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { ConnectionInfo, ConnectionStateInfo, JobInfo, ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { Connectivity } from '@/api/shared'
import CommonText from '@/components/CommonText.vue'
import ComponentWorkspaceTabs from '@/components/ComponentWorkspaceTabs.vue'
import ComponentWorkspacesSection from '@/components/ComponentWorkspacesSection.vue'
import FullPage from '@/components/FullPage.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import WorkspacePage from '@/pages/Workspace.vue'
import { usePersisted } from '@/persistence'
import { resolveTabs, useTabs } from '@/tabs'
import { utc } from '@/time'
import { highlight } from '@/utilities'
import { inStandardOrder, useWorkspaces, Workspace } from '@/workspace'

const engine = useEngine()
const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const navigation = useNavigation()
const route = useRoute()
const tabs = useTabs()
const workspaces = useWorkspaces()

const address = $computed(() => new Address(route.params.address as string))
const component = $computed(() => engine.components.get(address))

const effectiveAccess = $computed(() => access.levelFor(address.toString()))

const canManage = $computed(() => access.canManage(address.toString()))

// Adding a workspace here needs only view, because a user without manage gets a private one,
// which nobody else sees.
const canCreate = $computed(() => access.canView(address.toString()))

// Below this width the overview's two columns stack into one, which makes it roughly twice as
// tall. A height dragged on a wide screen then clips it mid-item, so there it sizes to its own
// content instead and the drag handle goes away with the drag.
const overviewColumnsMin = 720
const overviewStacks = useMediaQuery(`(max-width: ${overviewColumnsMin - 1}px)`)

// The shared default set for this component, in standard order.
let placedWorkspaces = $ref<Workspace[]>([])

// What this user's strip actually shows. The defaults are what someone who has never touched this
// strip sees, and their own set takes over from there.
const scopedWorkspaces = $computed(() =>
  resolveTabs(placedWorkspaces, tabs.setFor(address.toString()), (workspace) => workspace.id)
)

// Placed here but not in the strip, which is what the add button offers before creating one.
const openableWorkspaces = $computed(() => {
  const shown = new Set(scopedWorkspaces.map((workspace) => workspace.id))
  return placedWorkspaces.filter((workspace) => !shown.has(workspace.id))
})

async function openScoped(id: string) {
  await tabs.open(address.toString(), id)
  selectWorkspace(id)
}

// Only the workspace named in the URL is shown. Without one the page falls back to the first tab,
// so a component with workspaces opens on one rather than on a bare overview.
const activeWorkspaceId = $computed(() => {
  const value = navigation.route.query.workspace
  return typeof value === 'string' ? value : null
})

// With the overview open and no workspace beneath it, the tab strip sits at the bottom of the page
// rather than floating below the overview with empty space under it. Collapsing the overview
// leaves nothing to push it away from, so it goes back to the top.
const pinTabs = $computed(() => activeWorkspaceId == null && !persisted.overviewCollapsed)

function selectWorkspace(id: string) {
  void navigation.replace({ query: { workspace: id } })
}

async function refreshScoped() {
  placedWorkspaces = inStandardOrder(await workspaces.listScoped(address))
}

// Dragging positions this user's own tabs. The shared standard order lives in `data.meta.order`
// and is edited from the overview, so one user arranging their strip does not rearrange everyone
// else's.
async function reorderScoped(ordered: Workspace[]) {
  await tabs.reorder(
    address.toString(),
    ordered.map((workspace) => workspace.id)
  )
}

// Closing moves to whichever tab takes the closed one's place, or to the bare overview when it was
// the last one. The workspace itself is untouched, which is what separates closing from deleting.
async function closeScoped(id: string) {
  const remaining = scopedWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(address.toString(), id)

  if (activeWorkspaceId === id) {
    await navigation.replace({
      query: remaining.length > 0 ? { workspace: remaining[0].id } : {},
    })
  }
}

// Scoped workspaces are fetched separately from the store's own list, so the tabs are refetched
// whenever that list changes. The store refreshes it after every create, update, and delete,
// which covers a workspace being renamed or deleted from the tab shown below.
watch(
  () => workspaces.all,
  () => {
    void refreshScoped()
  }
)

// Landing on a component opens its first workspace. Closing the last tab clears the query
// entirely, which is what tells this apart from arriving with no workspace named, so closing
// leaves the overview showing rather than immediately reopening what was just closed.
watch(
  () => [activeWorkspaceId, scopedWorkspaces] as const,
  ([active, listed]) => {
    if (active == null && listed.length > 0 && navigation.route.query.workspace === undefined) {
      selectWorkspace(listed[0].id)
    }
  },
  { immediate: true }
)

function createScoped() {
  dialogs.createWorkspace(address.toString()).onOk(async (created: Workspace) => {
    await refreshScoped()
    selectWorkspace(created.id)
  })
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
    selectWorkspace(imported[0].id)
  }
}

await tabs.load()
await refreshScoped()

const queries = $computed(() => component?.procedures.filter((p) => p.type === 'query') ?? [])
const actions = $computed(() => component?.procedures.filter((p) => p.type === 'action') ?? [])

// Each procedure declares its own minimum level, listed here as reference rather than as a
// control, since procedures are invoked from workspaces and interfaces instead of this page.
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

  if (effectiveAccess == null) {
    return false
  }

  return permissionRank[effectiveAccess] >= permissionRank[procedure.permissions]
}

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

// The statuses stream pushes on lifecycle and connectivity events, so a refetch on each push keeps
// connection states and job schedules current without polling. Jobs are included because a
// component's scheduler stops and starts with it, changing each job's next run time.
watch(
  () => engine.statuses.get(address),
  () => {
    void connectionsQuery.refetch()
    void jobsQuery.refetch()
  }
)

const connections = $computed<(ConnectionInfo | ConnectionStateInfo)[]>(
  () => connectionsQuery.data.value ?? component?.connections ?? []
)

const connectivityColors: Record<Connectivity, string> = {
  connected: 'positive',
  connecting: 'warning',
  disconnected: 'negative',
}

const running = $computed(() => engine.statuses.get(address)?.running ?? false)

// A stopped component's connections are expectedly down, shown inert grey rather than alarming
// red, with the pulse stilled to match.
function connectivityColor(connectivity: Connectivity): string {
  return running ? connectivityColors[connectivity] : 'grey'
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
  configText == null ? null : highlight(configText, 'yaml')
)

// Persist each drawer's open state per component address. The page remounts on navigation between
// components (the page container is keyed by route path), so this re-reads for the new address.
const persisted = usePersisted({
  schema: ({ object, boolean, number }) =>
    object({
      configuration: boolean().default(true),
      connections: boolean().default(false),
      jobs: boolean().default(false),
      queries: boolean().default(false),
      actions: boolean().default(false),
      overviewCollapsed: boolean().default(false),
      overviewHeight: number().default(320),
    }),
  methods: computed(() => [
    { type: 'local-storage' as const, key: ['component-detail-drawers', address] },
  ]),
})
</script>

<template>
  <full-page :fill="pinTabs">
    <template #header-append>
      <common-text class="q-ml-md" variant="title2">
        {{ component?.address?.toString() ?? address.toString() }}
      </common-text>
      <status-badge v-if="component" :address class="q-ml-sm" :scale="0.65" />
      <q-separator class="q-ml-md" inset vertical />
      <q-btn
        class="q-ml-sm"
        :color="persisted.overviewCollapsed ? undefined : 'primary'"
        dense
        flat
        :icon="icons.overview"
        :icon-right="persisted.overviewCollapsed ? icons.menuDown : icons.menuUp"
        size="sm"
        @click="persisted.overviewCollapsed = !persisted.overviewCollapsed"
      >
        <q-tooltip
          >{{ persisted.overviewCollapsed ? 'Show' : 'Hide' }} the overview panel.</q-tooltip
        >
      </q-btn>
      <q-space />
      <q-chip
        v-if="effectiveAccess != null"
        class="q-mr-sm q-px-sm"
        color="primary"
        dense
        :icon="icons[effectiveAccess]"
        size="10px"
        text-color="white"
      >
        {{ upperFirst(effectiveAccess) }}
        <q-tooltip class="bg-primary text-white">
          You have permissions to {{ effectiveAccess }} this component.
        </q-tooltip>
      </q-chip>
    </template>

    <div v-if="component == null" class="q-pa-xl text-center text-grey-6">Component not found.</div>
    <template v-else>
      <div v-if="!persisted.overviewCollapsed" class="relative-position">
        <div
          :class="[$style.overviewContent, 'scroll']"
          :style="
            activeWorkspaceId != null && !overviewStacks
              ? { height: `${persisted.overviewHeight}px` }
              : undefined
          "
        >
          <div :class="[$style.overviewGrid, 'q-col-gutter-md', 'q-pa-md', 'row']">
            <div
              v-if="configHighlighted != null"
              :class="[$style.configColumn, persisted.configuration && $style.configFill]"
            >
              <q-list bordered class="rounded-borders" dense>
                <q-expansion-item
                  v-model="persisted.configuration"
                  dense
                  dense-toggle
                  label="Configuration"
                >
                  <!-- eslint-disable-next-line vue/no-v-html -->
                  <pre :class="$style.config"><code v-html="configHighlighted" /></pre>
                </q-expansion-item>
              </q-list>
            </div>

            <div :class="configHighlighted != null ? $style.detailsColumn : 'col-12'">
              <q-list bordered class="rounded-borders" dense>
                <q-expansion-item
                  v-model="persisted.connections"
                  dense
                  dense-toggle
                  :label="`Connections (${connections.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="connections.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No connections.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item
                      v-for="connection in connections"
                      :key="connection.name"
                      :class="$style.item"
                    >
                      <q-item-section>
                        <q-item-label>{{ connection.name }}</q-item-label>
                        <q-item-label caption>{{ connection.label }}</q-item-label>
                      </q-item-section>
                      <q-item-section v-if="'connectivity' in connection" side>
                        <span
                          :class="[
                            $style.dot,
                            !running && $style.still,
                            `bg-${connectivityColor(connection.connectivity)}`,
                          ]"
                        >
                          <q-tooltip :class="`bg-${connectivityColor(connection.connectivity)}`">
                            {{ upperFirst(connection.connectivity) }}
                          </q-tooltip>
                        </span>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
                <q-separator />
                <q-expansion-item
                  v-model="persisted.jobs"
                  dense
                  dense-toggle
                  :label="`Jobs (${jobs.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="jobs.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No jobs.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-for="job in jobs" :key="job.name" :class="$style.item">
                      <q-item-section>
                        <q-item-label>{{ job.name }}</q-item-label>
                        <q-item-label caption>{{ jobLabel(job) }}</q-item-label>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
              </q-list>

              <q-list bordered class="q-mt-md rounded-borders" dense>
                <q-expansion-item
                  v-model="persisted.queries"
                  dense
                  dense-toggle
                  :label="`Queries (${queries.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="queries.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No queries.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-for="query in queries" :key="query.name">
                      <q-item-section>
                        <q-item-label>{{ query.name }}</q-item-label>
                        <q-item-label caption>{{ permissionsLabel(query) }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <div class="items-center q-gutter-xs row">
                          <q-chip
                            v-if="query.live"
                            color="green"
                            dense
                            label="live"
                            size="10px"
                            text-color="white"
                          />
                          <q-icon
                            v-if="!canInvoke(query)"
                            class="text-grey-6"
                            :name="icons.locked"
                            size="16px"
                          >
                            <q-tooltip>Not available with your access.</q-tooltip>
                          </q-icon>
                        </div>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
                <q-separator />
                <q-expansion-item
                  v-model="persisted.actions"
                  dense
                  dense-toggle
                  :label="`Actions (${actions.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="actions.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No actions.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-for="action in actions" :key="action.name">
                      <q-item-section>
                        <q-item-label>{{ action.name }}</q-item-label>
                        <q-item-label caption>{{ permissionsLabel(action) }}</q-item-label>
                      </q-item-section>
                      <q-item-section v-if="!canInvoke(action)" side>
                        <q-icon class="text-grey-6" :name="icons.locked" size="16px">
                          <q-tooltip>Not available with your access.</q-tooltip>
                        </q-icon>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
                <q-separator />
                <component-workspaces-section
                  :can-manage="canManage"
                  :placement="address.toString()"
                  :workspaces="placedWorkspaces"
                  @open="selectWorkspace"
                />
              </q-list>

              <div v-if="component.tags.length > 0" class="q-mt-md">
                <div class="q-mb-xs text-subtitle2">Tags</div>
                <div class="q-gutter-xs row">
                  <q-chip
                    v-for="tag in component.tags"
                    :key="tag"
                    dense
                    :label="tag"
                    outline
                    size="sm"
                  />
                </div>
              </div>
            </div>

            <div v-if="component.components.length > 0" class="col-12">
              <div class="q-mb-xs text-subtitle2">Child Components</div>
              <q-list bordered class="rounded-borders" dense separator>
                <q-item
                  v-for="child in component.components"
                  :key="child.name"
                  clickable
                  :to="`/components/${child.address}`"
                >
                  <q-item-section>
                    <q-item-label>{{ child.name }}</q-item-label>
                    <q-item-label caption>{{ child.address }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <status-badge :address="new Address(child.address.toString())" />
                  </q-item-section>
                </q-item>
              </q-list>
            </div>
          </div>
        </div>
        <resize-handle
          v-if="activeWorkspaceId != null && !overviewStacks"
          v-model="persisted.overviewHeight"
          :class="$style.overviewResizeHandle"
          direction="vertical"
          :max="800"
          :min="120"
        />
      </div>
      <!-- Deliberately not keyed on the workspace ID. The workspace context follows its ID, so
      switching tabs updates this page in place and leaves the tab strip in its header mounted. -->
      <workspace-page v-if="activeWorkspaceId != null" :id="activeWorkspaceId">
        <template #header-prepend="{ actions, state }">
          <component-workspace-tabs
            :active="activeWorkspaceId"
            :active-actions="actions"
            :active-state="state"
            :can-create="canCreate"
            :can-manage="canManage"
            class="q-ml-sm"
            :openable="openableWorkspaces"
            :workspaces="scopedWorkspaces"
            @close="closeScoped"
            @create="createScoped"
            @import="importScoped"
            @open="openScoped"
            @reorder="reorderScoped"
            @select="selectWorkspace"
          />
        </template>
      </workspace-page>
      <div
        v-else-if="scopedWorkspaces.length > 0 || canCreate"
        :class="pinTabs && $style.pinnedTabs"
      >
        <q-separator />
        <component-workspace-tabs
          :active="activeWorkspaceId"
          :can-create="canCreate"
          :can-manage="canManage"
          class="q-px-sm q-py-xs"
          :openable="openableWorkspaces"
          :workspaces="scopedWorkspaces"
          @close="closeScoped"
          @create="createScoped"
          @import="importScoped"
          @open="openScoped"
          @reorder="reorderScoped"
          @select="selectWorkspace"
        />
      </div>
    </template>
  </full-page>
</template>

<style lang="scss" module>
// The config and connections blocks sit side by side above this width and stack below it.
$overview-columns-min: 720px;

// With a workspace below, the panel takes the height dragged onto it, set inline. On its own it
// grows with its content up to what is left of the viewport, then scrolls. This is a maximum
// rather than a fixed height so a collapsed configuration does not leave the panel padded out
// with empty space down to the fold.
.pinnedTabs {
  margin-top: auto;
}

.overviewContent {
  overflow-x: hidden;
  max-height: calc(100vh - 92px);
}

// The grid fills the panel so the configuration can reach its bottom edge, and grows past it
// when the other column is taller.
.overviewGrid {
  min-height: 100%;
}

.configColumn,
.detailsColumn {
  flex: 0 0 100%;
  max-width: 100%;
}

// An expanded configuration stretches to the bottom of the panel and scrolls its own contents,
// rather than ending wherever the file happens to end.
.configFill {
  display: flex;
  flex-direction: column;
  min-height: 0;

  > :global(.q-list),
  :global(.q-expansion-item),
  :global(.q-expansion-item__container) {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
  }

  :global(.q-expansion-item__content) {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
}

@media (min-width: $overview-columns-min) {
  .configColumn {
    flex-basis: 58.3333%;
    max-width: 58.3333%;
  }

  .detailsColumn {
    flex-basis: 41.6667%;
    max-width: 41.6667%;
  }
}

.overviewResizeHandle {
  position: absolute;
  bottom: 0;
  left: 0;
}

.item {
  padding-top: 6px;
  padding-bottom: 6px;
}

.config {
  margin: 0;
  overflow-x: auto;
  padding: 8px 12px 12px;
  font-size: 12px;
  line-height: 1.5;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
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
