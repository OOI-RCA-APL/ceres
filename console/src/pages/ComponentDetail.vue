<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { ConnectionInfo, ConnectionStateInfo, JobInfo, ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { Connectivity } from '@/api/shared'
import CardPage from '@/components/CardPage.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { utc } from '@/time'
import { highlight } from '@/utilities'

const engine = useEngine()
const access = useAccess()
const route = useRoute()

const address = $computed(() => new Address(route.params.address as string))
const component = $computed(() => engine.components.get(address))

const effectiveAccess = $computed(() => access.levelFor(address.toString()))

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

// The statuses stream pushes on connect, disconnect, and connect-failed events, so a refetch on
// each push keeps connection states current without polling.
watch(
  () => engine.statuses.get(address),
  () => {
    void connectionsQuery.refetch()
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

// Track which section groups have content so separators only render between non-empty groups.
const hasOverview = $computed(() => (component?.tags.length ?? 0) > 0)
const hasChildren = $computed(() => (component?.components.length ?? 0) > 0)

// Persist each drawer's open state per component address. The page remounts on navigation between
// components (the page container is keyed by route path), so this re-reads for the new address.
const persisted = usePersisted({
  schema: ({ object, boolean }) =>
    object({
      configuration: boolean().default(true),
      connections: boolean().default(false),
      jobs: boolean().default(false),
      queries: boolean().default(false),
      actions: boolean().default(false),
    }),
  methods: computed(() => [
    { type: 'local-storage' as const, key: ['component-detail-drawers', address] },
  ]),
})
</script>

<template>
  <card-page :title="component?.address?.toString() ?? address.toString()">
    <template #header-append>
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
      <status-badge v-if="component" :address :scale="0.75" />
    </template>
    <q-card-section v-if="component == null">
      <div class="text-grey-6">Component not found.</div>
    </q-card-section>

    <template v-else>
      <template v-if="configHighlighted != null">
        <q-card-section>
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
        </q-card-section>
        <q-separator />
      </template>

      <q-card-section>
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
              <q-item v-for="connection in connections" :key="connection.name" :class="$style.item">
                <q-item-section>
                  <q-item-label>{{ connection.label }}</q-item-label>
                  <q-item-label caption>{{ connection.name }}</q-item-label>
                </q-item-section>
                <q-item-section v-if="'connectivity' in connection" side>
                  <span :class="[$style.dot, `bg-${connectivityColors[connection.connectivity]}`]">
                    <q-tooltip>{{ upperFirst(connection.connectivity) }}</q-tooltip>
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
      </q-card-section>

      <q-separator />

      <q-card-section v-if="component.tags.length > 0">
        <div class="q-mb-xs text-subtitle2">Tags</div>
        <div class="q-gutter-xs row">
          <q-chip v-for="tag in component.tags" :key="tag" dense :label="tag" outline size="sm" />
        </div>
      </q-card-section>

      <q-separator v-if="hasOverview" />

      <q-card-section>
        <q-list bordered class="rounded-borders" dense>
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
        </q-list>
      </q-card-section>

      <q-separator v-if="hasChildren" />

      <q-card-section v-if="component.components.length > 0">
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
      </q-card-section>
    </template>
  </card-page>
</template>

<style lang="scss" module>
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
  width: 10px;
  height: 10px;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
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
