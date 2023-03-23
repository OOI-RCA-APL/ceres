<template>
  <full-page :title="title">
    <template #header-append>
      <q-space />
      <unit-controls v-if="unit" class="q-mr-md" :unit-name="unit.name" />
    </template>
    <div v-if="components.length === 0" class="q-pa-md">
      <q-chip>No configuration found.</q-chip>
    </div>
    <div v-else-if="unit">
      <panel-group
        v-if="connections.length"
        :default-height="300"
        :panels="connections.map((current) => current.name)"
        :persist="`units/${unit.name}/messages-panel-group`"
        title="Messages"
      >
        <template #tabs>
          <panel-tab
            v-for="connection in connections"
            :key="connection.address"
            :name="connection.name"
          />
        </template>
        <panel
          v-for="connection in connections"
          :key="connection.address"
          class="column"
          :name="connection.name"
        >
          <item-view
            class="col-grow"
            :component-name="connection.name"
            kind="message"
            :title="connection.name"
            :unit-name="unit.name"
          />
        </panel>
      </panel-group>
      <panel-group
        v-if="alerters.length"
        :default-height="300"
        :panels="alerters.map((current) => current.name)"
        :persist="`units/${unit.name}/alert-panel-group`"
        title="Alerts"
      >
        <template #tabs>
          <panel-tab v-for="alerter in alerters" :key="alerter.address" :name="alerter.name">
            {{ alerter.name }}
            <alerts-indicator :component-name="alerter.name" :unit-name="unit.name" />
          </panel-tab>
        </template>
        <panel
          v-for="alerter in alerters"
          :key="alerter.address"
          class="column"
          :name="alerter.name"
        >
          <item-view
            class="col-grow"
            :component-name="alerter.name"
            kind="alert"
            :title="alerter.name"
            :unit-name="unit.name"
          />
        </panel>
      </panel-group>
      <panel-group
        v-if="components.length"
        :panels="components.map((current) => current.name)"
        :persist="`units/${unit.name}/actions-panel-group`"
        title="Actions"
      >
        <template #tabs>
          <panel-tab
            v-for="component in components"
            :key="component.address"
            :name="component.name"
          >
            {{ component.name }}
          </panel-tab>
        </template>
        <panel
          v-for="component in components"
          :key="component.address"
          class="column"
          :name="component.name"
        >
          <component-procedures class="col" :component="component" kind="action" />
        </panel>
      </panel-group>
      <panel-group
        v-if="uis.length"
        :panels="uis.map((current) => current.name)"
        :persist="`units/${unit.name}/displays-panel-group`"
        title="UI"
      >
        <template #tabs>
          <panel-tab v-for="hud in uis" :key="hud.address" :name="hud.name" />
        </template>
        <panel v-for="ui in uis" :key="ui.address" :name="ui.name">
          <div>
            <layout :component-name="ui.name" :unit-name="unit.name" />
          </div>
        </panel>
      </panel-group>
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
              <q-td class="self-name-column">{{ component.name }}</q-td>
              <q-td class="text-capitalize">Yes</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </div>
    </div>
  </full-page>
</template>

<script lang="ts" setup>
import { getUnit } from '@/api/operations'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import ComponentProcedures from '@/components/ComponentProcedures.vue'
import FullPage from '@/components/FullPage.vue'
import ItemView from '@/components/ItemView.vue'
import Layout from '@/components/Layout.vue'
import Panel from '@/components/Panel.vue'
import PanelGroup from '@/components/PanelGroup.vue'
import PanelTab from '@/components/PanelTab.vue'
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

  return name
})

const components = $computed(() => unit?.components ?? [])
const connections = $computed(() =>
  components.filter((component) => component.roles.includes('connection'))
)
const alerters = $computed(() =>
  components.filter((component) => component.roles.includes('alerter'))
)
const uis = $computed(() => components.filter((component) => component.roles.includes('ui')))
</script>

<style lang="scss" scoped>
.self-name-column {
  max-width: 50px;
}
</style>
