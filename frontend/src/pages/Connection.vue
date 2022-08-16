<template>
  <div>
    <common-text class="q-ml-md q-my-xs" variant="title2">{{ title }}</common-text>
    <q-separator />
    <div v-if="unit && connection" class="q-pa-md">
      <q-markup-table bordered class="q-mb-sm" dense flat separator="vertical">
        <thead>
          <q-tr no-hover>
            <q-th class="text-left">State</q-th>
            <q-th class="text-left">Enable</q-th>
            <q-th class="text-left">Target</q-th>
          </q-tr>
        </thead>
        <tbody>
          <q-tr no-hover>
            <q-td class="text-capitalize">{{ connection.state }}</q-td>
            <q-td>
              <q-toggle v-model="connection.enabled" class="q-ml-sm" dense />
            </q-td>
            <q-td>{{ connection.target }}</q-td>
          </q-tr>
        </tbody>
      </q-markup-table>
      <message-view
        :connection-name="connectionName"
        container-class="connections-page-message-view-container"
        title="Messages"
        :unit-name="unitName"
      />
    </div>
  </div>
</template>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import MessageView from '@/components/MessageView.vue'
import mock from '@/mock'

const { unitName, connectionName } = defineProps<{
  unitName: string
  connectionName: string
}>()

const unit = $computed(() => {
  return mock.config.units[unitName] ?? null
})

const connection = $computed(() => {
  if (unit == null) {
    return null
  }

  return unit.connections[connectionName] ?? null
})

const title = $computed(() => {
  if (unit == null) {
    return `Unit "${unitName}" does not exist.`
  }

  if (connection == null) {
    return `Connection "${connectionName}" does not exist.`
  }

  return `@${unitName}.connections.${connectionName}`
})
</script>

<style lang="scss">
.connections-page-message-view-container {
  height: 400px;
}
</style>
