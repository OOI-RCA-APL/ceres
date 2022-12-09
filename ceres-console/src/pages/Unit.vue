<template>
  <full-page :title="title">
    <template #header-append>
      <q-space />
      <unit-controls v-if="name && unit" class="q-mr-md" :unit-name="name" />
    </template>
    <div v-if="components.length === 0" class="q-pa-md">
      <q-chip>No configuration found.</q-chip>
    </div>
    <div v-else-if="unit" class="q-pa-md">
      <q-markup-table
        v-if="connections.length"
        bordered
        class="q-mb-sm"
        dense
        flat
        separator="vertical"
      >
        <thead>
          <q-tr no-hover>
            <q-th class="self-name-column text-left">Connection</q-th>
            <q-th class="text-left">Enabled</q-th>
            <q-th class="text-left">State</q-th>
            <q-th class="text-left">Target</q-th>
          </q-tr>
        </thead>
        <tbody>
          <q-tr v-for="connection in connections" :key="connection.name" no-hover>
            <router-link class="text-link" :to="`/units/${name}/components/${connection.name}`">
              <q-td class="self-name-column">@{{ name }}.{{ connection.name }}</q-td>
            </router-link>
            <q-td class="text-capitalize">Yes</q-td>
            <q-td class="text-capitalize">Unknown</q-td>
            <td>Unknown</td>
          </q-tr>
        </tbody>
      </q-markup-table>
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
  </full-page>
</template>

<script lang="ts" setup>
import { useConfig } from '@/api/queries'
import FullPage from '@/components/FullPage.vue'
import UnitControls from '@/components/UnitControls.vue'

const config = useConfig()

const { name = null } = defineProps<{
  name?: string | null
}>()

const unit = $computed(() => config.data.units.find((unit) => unit.name === name) ?? null)

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
</script>

<style lang="scss" scoped>
.self-name-column {
  max-width: 50px;
}
</style>
