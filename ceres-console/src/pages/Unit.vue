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
        <div class="q-px-md q-py-sm text-grey-8">Connections</div>
        <q-btn
          v-for="connection in connections"
          :key="connection.name"
          :class="[
            'q-px-md',
            selectedConnectionNames.includes(connection.name) ? 'text-primary' : '',
          ]"
          dense
          flat
          :icon="
            selectedConnectionNames.includes(connection.name) ? 'arrow_drop_up' : 'arrow_drop_down'
          "
          no-caps
          square
          :style="{ fontWeight: '400' }"
          @click="
            selectedConnectionNames = selectedConnectionNames.includes(connection.name)
              ? selectedConnectionNames.filter((current) => current !== connection.name)
              : [...selectedConnectionNames, connection.name]
          "
        >
          {{ `@${name}.${connection.name}` }}
        </q-btn>
      </div>
      <template v-if="selectedConnectionNames.length">
        <q-separator />
        <div class="row">
          <q-tab-panel
            v-for="selectedConnectionName in selectedConnectionNames"
            :key="selectedConnectionName"
            class="col q-pa-sm"
            :name="selectedConnectionName"
          >
            <message-view
              :component-name="selectedConnectionName"
              container-class="component-page-message-view-container"
              title="Messages"
              :unit-name="name"
            />
          </q-tab-panel>
        </div>
      </template>
      <div class="q-pa-md">
        <q-markup-table v-if="components.length" bordered dense flat separator="vertical">
          <thead>
            <q-tr no-hover>
              <q-th class="self-name-column text-left">Component</q-th>
              <q-th class="text-left">Enabled</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr v-for="component in components" :key="component.name" no-hover>
              <router-link class="text-link" :to="`/units/${name}/components/${component.name}`">
                <q-td class="self-name-column">@{{ name }}.{{ component.name }}</q-td>
              </router-link>
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
import MessageView from '@/components/MessageView.vue'
import UnitControls from '@/components/UnitControls.vue'
import { useQuery } from 'vue-query'

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
  components.filter((component) => component.config.roles.includes('connection'))
)

let selectedConnectionNames = $ref<string[]>(connections.length ? [connections[0].config.name] : [])
</script>

<style lang="scss" scoped>
.self-name-column {
  max-width: 50px;
}
</style>
