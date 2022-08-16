<template>
  <full-page :title="title">
    <template #header-append>
      <q-space />
      <unit-controls v-if="name && unit" class="q-mr-md" :unit-name="name" />
    </template>
    <div v-if="isBlank" class="q-pa-md">
      <q-chip>No configuration found.</q-chip>
    </div>
    <div v-else-if="unit" class="q-pa-md">
      <section-card v-if="connectionCount > 0" class="q-mb-sm" padding title="Connections">
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
      </section-card>
      <section-card v-if="driverCount > 0" class="q-mb-sm" padding title="Dashboard">
        <template v-for="(driver, name) in unit.drivers" :key="name">
          <dashboard :elements="driver.elements" />
        </template>
      </section-card>
      <section-card padding title="Scheduled Jobs">
        <q-markup-table bordered dense flat separator="cell">
          <thead>
            <q-tr no-hover>
              <q-th class="text-left">Job</q-th>
              <q-th class="text-left">Last Run</q-th>
              <q-th class="text-left">Next Run</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr no-hover>
              <q-td>sync-configuration</q-td>
              <q-td>{{ moment.utc().add(0.5, 'hours').format('YYYY/MM/DD HH:DD:ss') }} UTC</q-td>
              <q-td>{{ moment.utc().add(1, 'hours').format('YYYY/MM/DD HH:DD:ss') }} UTC</q-td>
            </q-tr>
            <q-tr no-hover>
              <q-td>power-cycle</q-td>
              <q-td>{{
                moment
                  .utc()
                  .add(1, 'days')
                  .set({
                    hour: 0,
                    minute: 0,
                    second: 0,
                    milliseconds: 0,
                  })
                  .format('YYYY/MM/DD HH:DD:ss UTC')
              }}</q-td>
              <q-td>{{
                moment
                  .utc()
                  .add(2, 'days')
                  .set({
                    hour: 0,
                    minute: 0,
                    second: 0,
                    milliseconds: 0,
                  })
                  .format('YYYY/MM/DD HH:DD:ss UTC')
              }}</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </section-card>
    </div>
  </full-page>
</template>

<script lang="ts" setup>
import Dashboard from '@/components/Dashboard.vue'
import SectionCard from '@/components/SectionCard.vue'
import mock from '@/mock'
import moment from 'moment'
import FullPage from '@/components/FullPage.vue'
import UnitControls from '@/components/UnitControls.vue'

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
