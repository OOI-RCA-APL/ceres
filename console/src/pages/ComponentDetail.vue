<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import icons from '@/icons'
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

// Configuration can carry credentials in component arguments, so the endpoint requires manage
// access. Failures are expected for everyone else and simply hide the section.
const configQuery = useQuery({
  queryKey: computed(() => ['component-config', address.toString()]),
  queryFn: () => engine.components.getConfig(address),
  retry: false,
})

const configText = $computed(() => {
  const config = configQuery.data.value
  if (config == null) {
    return null
  }

  return JSON.stringify(config, null, 2)
})

const configHighlighted = $computed(() =>
  configText == null ? null : highlight(configText, 'json')
)

// Track which section groups have content so separators only render between non-empty groups.
const hasOverview = $computed(() => (component?.tags.length ?? 0) > 0 || effectiveAccess != null)
const hasProcedures = $computed(() => queries.length > 0 || actions.length > 0)
const hasConnectivity = $computed(
  () => (component?.connections.length ?? 0) > 0 || (component?.components.length ?? 0) > 0
)
</script>

<template>
  <card-page :title="component?.address?.toString() ?? address.toString()">
    <template #header-append>
      <q-space />
      <status-badge v-if="component" :address />
    </template>
    <q-card-section v-if="component == null">
      <div class="text-grey-6">Component not found.</div>
    </q-card-section>

    <template v-else>
      <q-card-section v-if="component.tags.length > 0">
        <div class="q-mb-xs text-subtitle2">Tags</div>
        <div class="q-gutter-xs row">
          <q-chip v-for="tag in component.tags" :key="tag" dense :label="tag" outline size="sm" />
        </div>
      </q-card-section>

      <q-card-section v-if="effectiveAccess != null">
        <div class="q-mb-xs text-subtitle2">Your Access</div>
        <q-chip
          class="q-px-sm"
          color="primary"
          dense
          :icon="icons[effectiveAccess]"
          size="10px"
          text-color="white"
        >
          {{ upperFirst(effectiveAccess) }}
        </q-chip>
      </q-card-section>

      <q-separator v-if="hasOverview && hasProcedures" />

      <q-card-section v-if="hasProcedures">
        <q-list bordered class="rounded-borders" dense>
          <q-expansion-item
            v-if="queries.length > 0"
            dense
            dense-toggle
            :label="`Queries (${queries.length})`"
          >
            <q-list class="q-pb-sm" dense>
              <q-item v-for="query in queries" :key="query.name">
                <q-item-section>
                  <q-item-label>{{ query.name }}</q-item-label>
                  <q-item-label caption>{{ permissionsLabel(query) }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-chip
                    v-if="query.live"
                    color="green"
                    dense
                    label="live"
                    size="10px"
                    text-color="white"
                  />
                </q-item-section>
              </q-item>
            </q-list>
          </q-expansion-item>
          <q-separator v-if="queries.length > 0 && actions.length > 0" />
          <q-expansion-item
            v-if="actions.length > 0"
            dense
            dense-toggle
            :label="`Actions (${actions.length})`"
          >
            <q-list class="q-pb-sm" dense>
              <q-item v-for="action in actions" :key="action.name">
                <q-item-section>
                  <q-item-label>{{ action.name }}</q-item-label>
                  <q-item-label caption>{{ permissionsLabel(action) }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-expansion-item>
        </q-list>
      </q-card-section>

      <q-separator v-if="(hasOverview || hasProcedures) && hasConnectivity" />

      <q-card-section v-if="component.connections.length > 0">
        <div class="q-mb-xs text-subtitle2">Connections</div>
        <q-list bordered class="rounded-borders" dense separator>
          <q-item v-for="connection in component.connections" :key="connection.name">
            <q-item-section>
              <q-item-label>{{ connection.label }}</q-item-label>
              <q-item-label caption>{{ connection.name }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

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

      <template v-if="configHighlighted != null">
        <q-separator />
        <q-card-section>
          <q-list bordered class="rounded-borders" dense>
            <q-expansion-item dense dense-toggle label="Configuration">
              <!-- eslint-disable-next-line vue/no-v-html -->
              <pre :class="$style.config"><code v-html="configHighlighted" /></pre>
            </q-expansion-item>
          </q-list>
        </q-card-section>
      </template>
    </template>
  </card-page>
</template>

<style lang="scss" module>
.config {
  margin: 0;
  overflow-x: auto;
  padding: 8px 12px 12px;
  font-size: 12px;
  line-height: 1.5;
}
</style>
