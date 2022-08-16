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
            <q-tr no-hover>
              <q-th class="text-left">Connection</q-th>
              <q-th class="text-left">State</q-th>
              <q-th class="text-left">Enable</q-th>
              <q-th class="text-left">Target</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr
              v-for="(connection, connectionName) in unit.connections"
              :key="connectionName"
              no-hover
            >
              <router-link class="text-link" :to="`/units/${name}/connections/${connectionName}`">
                <td>{{ connectionName }}</td>
              </router-link>
              <q-td class="text-capitalize">{{ connection.state }}</q-td>
              <q-td>
                <q-toggle v-model="connection.enabled" class="q-ml-sm" dense />
              </q-td>
              <td>{{ connection.target }}</td>
            </q-tr>
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
import CommonText from '@/components/CommonText.vue'
import Dashboard from '@/components/Dashboard.vue'
import mock from '@/mock'

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

  return `@${name}`
})

const connectionCount = $computed(() => Object.values(unit?.connections ?? []).length)
const driverCount = $computed(() => Object.values(unit?.drivers ?? []).length)
const pipelineCount = $computed(() => Object.values(unit?.pipelines ?? []).length)

const isBlank = $computed(() => connectionCount + driverCount + pipelineCount === 0)
</script>
