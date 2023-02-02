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
        <div class="q-px-md q-py-sm text-grey-8" style="min-width: 120px">Connections</div>
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
          {{ `@${name}.${connection.name}` }}
        </q-btn>
      </div>
      <template v-if="state.selectedConnectionNames.length">
        <q-separator />
        <div class="row">
          <q-tab-panel
            v-for="selectedConnectionName in state.selectedConnectionNames"
            :key="selectedConnectionName"
            class="col q-pa-sm"
            :name="selectedConnectionName"
          >
            <message-view
              :component-name="selectedConnectionName"
              container-class="unit-page-message-view-container"
              title="Messages"
              :unit-name="name"
            />
          </q-tab-panel>
        </div>
      </template>
      <q-separator />
      <div class="relative-position row">
        <div class="q-px-md q-py-sm text-grey-8" style="min-width: 120px">Drivers</div>
        <q-separator vertical />
        <q-btn
          v-for="driver in drivers"
          :key="driver.name"
          :class="[
            'q-px-md',
            state.selectedDriverNames.includes(driver.name) ? 'text-primary' : '',
          ]"
          dense
          flat
          :icon="
            state.selectedDriverNames.includes(driver.name) ? 'arrow_drop_up' : 'arrow_drop_down'
          "
          no-caps
          square
          :style="{ fontWeight: '400' }"
          @click="
            state.selectedDriverNames = state.selectedDriverNames.includes(driver.name)
              ? state.selectedDriverNames.filter((current) => current !== driver.name)
              : [...state.selectedDriverNames, driver.name]
          "
        >
          {{ `@${name}.${driver.name}` }}
        </q-btn>
      </div>
      <template v-if="state.selectedDriverNames.length">
        <q-separator />
        <div class="row">
          <q-tab-panel
            v-for="driver in drivers.filter((driver) =>
              state.selectedDriverNames.includes(driver.name)
            )"
            :key="driver.name"
            class="col q-pa-sm"
            :name="driver.name"
          >
            <div
              v-for="(displays, group) in getDisplayGroups(driver)"
              :key="group"
              class="col q-gutter-xs q-mb-sm row-sm"
            >
              <display
                v-for="display in displays"
                :key="display.name"
                class="col"
                :component-name="driver.name"
                :display-name="display.name"
                :unit-name="name"
              />
            </div>
            <div
              v-for="display in driver.displays.filter((display) => display.group == null)"
              :key="display.name"
              class="col q-gutter-xs q-mb-sm row"
            >
              <display
                :key="display.name"
                class="col"
                :component-name="driver.name"
                :display-name="display.name"
                :unit-name="name"
              />
            </div>
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
              <q-td class="self-name-column">@{{ name }}.{{ component.name }}</q-td>
              <q-td class="text-capitalize">Yes</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </div>
    </div>
  </full-page>
</template>

<script lang="ts" setup>
import { ComponentInfo, DisplayBinding } from '@/api/models'
import { getUnit } from '@/api/queries'
import Display from '@/components/Display.vue'
import FullPage from '@/components/FullPage.vue'
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

  return `@${name}`
})

const components = $computed(() => unit?.components ?? [])
const connections = $computed(() =>
  components.filter((component) => component.roles.includes('connection'))
)
const drivers = $computed(() => components.filter((component) => component.displays.length))

const StateSchema = Zod.object({
  selectedConnectionNames: Zod.array(Zod.string()).default(() =>
    connections.length ? [connections[0].name] : []
  ),
  selectedDriverNames: Zod.array(Zod.string()).default(() =>
    drivers.length ? [drivers[0].name] : []
  ),
})

const state = usePersisted({
  schema: StateSchema,
  methods: computed(() => [{ type: 'local-storage', key: `unit:${name}` }]),
})

function getDisplayGroups(driver: ComponentInfo) {
  const groups: Record<string, DisplayBinding[]> = {}
  for (const display of driver.displays) {
    if (display.group == null) {
      continue
    }
    if (!(display.group in groups)) {
      groups[display.group] = []
    }

    groups[display.group].push(display)
  }

  const defaultGroup = groups['default']
  delete groups['default']
  if (defaultGroup != null) {
    groups['default'] = defaultGroup
  }

  return groups
}
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
