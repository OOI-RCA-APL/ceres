<template>
  <full-page :title="title">
    <template #header-append>
      <q-space />
      <unit-controls v-if="name && unit" class="q-mr-md" :unit-name="name" />
    </template>
    <div v-if="components.length === 0" class="q-pa-md">
      <q-chip>No configuration found.</q-chip>
    </div>
    <div v-else-if="unit && name">
      <div class="relative-position row">
        <div class="q-px-md q-py-sm text-grey-8" style="min-width: 120px">Messages</div>
        <q-separator vertical />
        <q-btn
          v-for="connection in connections"
          :key="connection.name"
          :class="[
            'q-px-md',
            state.selectedConnectionNames.includes(connection.name) ? 'text-primary' : '',
          ]"
          dense
          flat
          :icon="
            state.selectedConnectionNames.includes(connection.name)
              ? 'arrow_drop_up'
              : 'arrow_drop_down'
          "
          no-caps
          square
          :style="{ fontWeight: '400' }"
          @click="
            state.selectedConnectionNames = state.selectedConnectionNames.includes(connection.name)
              ? state.selectedConnectionNames.filter((current) => current !== connection.name)
              : [...state.selectedConnectionNames, connection.name]
          "
        >
          {{ `${unit.name}.${connection.name}` }}
        </q-btn>
      </div>
      <template v-if="state.selectedConnectionNames.length">
        <q-separator />
        <div class="row">
          <q-tab-panel
            v-for="connection in connections.filter((connection) =>
              state.selectedConnectionNames.includes(connection.name)
            )"
            :key="connection.name"
            class="col q-pa-sm"
            :name="connection.name"
          >
            <message-view
              :component-name="connection.name"
              container-class="unit-page-message-view-container"
              :title="`${unit.name}.${connection.name}`"
              :unit-name="name"
            />
          </q-tab-panel>
        </div>
      </template>
      <q-separator />
      <div class="relative-position row">
        <div class="q-px-md q-py-sm text-grey-8" style="min-width: 120px">Displays</div>
        <q-separator vertical />
        <q-btn
          v-for="hud in huds"
          :key="hud.name"
          :class="['q-px-md', state.selectedHudNames.includes(hud.name) ? 'text-primary' : '']"
          dense
          flat
          :icon="state.selectedHudNames.includes(hud.name) ? 'arrow_drop_up' : 'arrow_drop_down'"
          no-caps
          square
          :style="{ fontWeight: '400' }"
          @click="
            state.selectedHudNames = state.selectedHudNames.includes(hud.name)
              ? state.selectedHudNames.filter((current) => current !== hud.name)
              : [...state.selectedHudNames, hud.name]
          "
        >
          {{ `${unit.name}.${hud.name}` }}
        </q-btn>
      </div>
      <template v-if="state.selectedHudNames.length">
        <q-separator />
        <div class="row">
          <q-tab-panel
            v-for="hud in huds.filter((hud) => state.selectedHudNames.includes(hud.name))"
            :key="hud.name"
            class="col q-pa-sm"
            :name="hud.name"
          >
            <layout :component-name="hud.name" :layout="hud.layout" :unit-name="unit.name" />
          </q-tab-panel>
        </div>
      </template>
      <q-separator />
      <div class="q-mt-lg q-pa-md">
        <q-markup-table v-if="components.length" bordered dense flat separator="vertical">
          <thead>
            <q-tr no-hover>
              <q-th class="self-name-column text-left">Component</q-th>
              <q-th class="text-left">Enabled</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr v-for="component in components" :key="component.name" no-hover>
              <q-td class="self-name-column">{{ name }}.{{ component.name }}</q-td>
              <q-td class="text-capitalize">Yes</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </div>
    </div>
  </full-page>
</template>

<script lang="ts" setup>
import { getUnit } from '@/api/queries'
import FullPage from '@/components/FullPage.vue'
import Layout from '@/components/Layout.vue'
import MessageView from '@/components/MessageView.vue'
import UnitControls from '@/components/UnitControls.vue'
import { usePersisted } from '@/persistence'
import { computed } from 'vue'
import { useQuery } from 'vue-query'
import Zod from 'zod'

const { name = null } = defineProps<{
  name?: string | null
}>()

const query = useQuery(['getUnit', name], async () => (name == null ? null : await getUnit(name)))
await query.suspense()

const unit = $computed(() => query.data?.value ?? null)

const title = $computed(() => {
  if (name == null) {
    return 'No unit is selected.'
  }

  if (unit == null) {
    return `Unit "${name}" does not exist.`
  }

  return name
})

const components = $computed(() => unit?.components ?? [])
const connections = $computed(() =>
  components.filter((component) => component.roles.includes('connection'))
)
const huds = $computed(() => components.filter((component) => component.displays.length))

const StateSchema = Zod.object({
  selectedConnectionNames: Zod.array(Zod.string()).default(() =>
    connections.length ? [connections[0].name] : []
  ),
  selectedHudNames: Zod.array(Zod.string()).default(() => (huds.length ? [huds[0].name] : [])),
})

const state = usePersisted({
  schema: StateSchema,
  methods: computed(() => [{ type: 'local-storage', key: `unit:${name}` }]),
})
</script>

<style lang="scss" scoped>
.self-name-column {
  max-width: 50px;
}
</style>

<style lang="scss">
.unit-page-message-view-container {
  height: 400px;
}
</style>
