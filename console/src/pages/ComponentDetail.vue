<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import icons from '@/icons'

const engine = useEngine()
const route = useRoute()

const address = $computed(() => new Address(route.params.address as string))
const component = $computed(() => engine.components.get(address))

const effectiveAccessQuery = useQuery({
  queryKey: computed(() => ['effective-access', engine.auth.user?.id, address.toString()]),
  queryFn: async () => {
    if (engine.auth.user == null) {
      return null
    }

    return await engine.permissions.getEffectiveAccess(engine.auth.user.id, address.toString())
  },
  enabled: computed(() => engine.auth.user != null),
})

const effectiveAccess = $computed(() => effectiveAccessQuery.data.value?.level ?? null)
const canOperate = $computed(() => effectiveAccess === 'operate' || effectiveAccess === 'manage')

const queries = $computed(() => component?.procedures.filter((p) => p.type === 'query') ?? [])
const actions = $computed(() => component?.procedures.filter((p) => p.type === 'action') ?? [])

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
      <status-badge v-if="component" :address :readonly="!canOperate" />
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

      <q-card-section v-if="queries.length > 0">
        <div class="q-mb-xs text-subtitle2">Queries</div>
        <q-list bordered class="rounded-borders" dense separator>
          <q-item v-for="query in queries" :key="query.name">
            <q-item-section>
              <q-item-label>{{ query.name }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-chip v-if="query.live" color="green" dense label="live" text-color="white" />
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <q-card-section v-if="actions.length > 0">
        <div class="q-mb-xs text-subtitle2">Actions</div>
        <q-list bordered class="rounded-borders" dense separator>
          <q-item v-for="act in actions" :key="act.name">
            <q-item-section>
              <q-item-label>{{ act.name }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-chip v-if="!canOperate" color="grey" dense label="no access" text-color="white" />
            </q-item-section>
          </q-item>
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
    </template>
  </card-page>
</template>
