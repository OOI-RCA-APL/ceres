<template>
  <common-text class="q-ml-md q-my-xs" variant="title2">{{ title }}</common-text>
  <q-separator />
  <div v-if="isBlank" class="q-pa-md">
    <q-chip>No configuration found.</q-chip>
  </div>
  <div v-else-if="unit" class="q-pa-md">
    <q-card v-if="connectionCount > 0" bordered class="q-mb-sm q-pa-md" flat>
      <div>
        <common-text class="q-mb-sm" variant="title2">Connections</common-text>
        <q-markup-table bordered dense flat separator="vertical">
          <thead>
            <tr>
              <th class="text-left">Connection</th>
              <th class="text-left">State</th>
              <th class="text-left">Enabled</th>
              <th class="text-left">Target</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(connection, name) in unit.connections" :key="name">
              <td>{{ name }}</td>
              <td class="text-capitalize">{{ connection.state }}</td>
              <td>
                <q-checkbox v-model="connection.enabled" class="q-ml-sm" dense />
              </td>
              <td>{{ connection.target }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </div>
    </q-card>
    <q-card v-if="driverCount > 0" bordered class="q-mb-sm q-pa-md" flat>
      <div>
        <common-text class="q-mb-sm" variant="title2">Dashboard</common-text>
      </div>
      <template v-for="(driver, name) in unit.drivers" :key="name">
        <dashboard :elements="driver.elements" />
      </template>
    </q-card>
  </div>
</template>

<script lang="ts" setup>
import CommonText from '../components/CommonText.vue'
import Dashboard from '../components/Dashboard.vue'
import mock from '../mock'

const { name = null } = defineProps<{
  name?: string | null
}>()

const unit = $computed(() => {
  if (name == null) {
    return null
  }

  return mock.config.units[name] ?? null
})

const title = $computed(() => {
  if (name == null) {
    return 'No unit is selected.'
  }

  if (unit == null) {
    return `Unit "${name}" does not exist.`
  }

  if (unit.label) {
    return `${unit.label} (@${name})`
  }

  return `@${name}`
})

const connectionCount = $computed(() => Object.values(unit?.connections ?? []).length)

const driverCount = $computed(() => Object.values(unit?.drivers ?? []).length)

const pipelineCount = $computed(() => Object.values(unit?.pipelines ?? []).length)

const isBlank = $computed(() => connectionCount + driverCount + pipelineCount === 0)
</script>
