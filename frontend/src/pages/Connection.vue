<template>
  <full-page :title="title">
    <template #header-append>
      <q-chip
        v-if="connection"
        class="q-ml-sm text-capitalize"
        clickable
        :color="connection.enabled ? 'primary' : 'grey'"
        dense
        text-color="white"
        @click="connection && (connection.enabled = !connection.enabled)"
      >
        {{ connection.enabled ? 'Enabled' : 'Disabled' }}
      </q-chip>
      <q-chip
        v-if="connection && connection.enabled"
        class="q-ml-xs text-capitalize"
        :color="connection.state === 'connected' ? 'positive' : 'warning'"
        dense
        text-color="white"
      >
        {{ connection.state }}
      </q-chip>
      <q-space />
      <unit-controls v-if="unit" class="q-mr-md" :unit-name="unitName" />
    </template>
    <div class="q-pa-md">
      <section-card v-if="unit && connection" class="q-mb-sm" padding title="Info">
        <q-markup-table bordered class="q-mb-sm" dense flat separator="vertical">
          <thead>
            <q-tr no-hover>
              <q-th class="text-left">Target</q-th>
              <q-th class="text-left">Connected At</q-th>
              <q-th class="text-left">Total Message Count</q-th>
              <q-th class="text-left">Messages Today</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr no-hover>
              <q-td>{{ connection.target }}</q-td>
              <q-td>{{ moment.utc().subtract(5, 'minutes').format('YYYY/MM/DD HH:mm:ss') }}</q-td>
              <q-td>{{ messageCount }}</q-td>
              <q-td>{{ messageCount }}</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </section-card>
      <message-view
        :connection-name="connectionName"
        container-class="connections-page-message-view-container"
        :message-count="100"
        title="Messages"
        :unit-name="unitName"
      />
    </div>
  </full-page>
</template>

<script lang="ts" setup>
import MessageView from '@/components/MessageView.vue'
import mock from '@/mock'
import moment from 'moment'
import FullPage from '@/components/FullPage.vue'
import UnitControls from '@/components/UnitControls.vue'
import SectionCard from '@/components/SectionCard.vue'

const { unitName, connectionName } = defineProps<{
  unitName: string
  connectionName: string
}>()

const messageCount = 100

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
