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
import { computed } from 'vue'
import { useQuery } from 'vue-query'

const { name = null } = defineProps<{
  name?: string | null
}>()

const query = useQuery(['getUnit', computed(() => name)], async () =>
  name == null ? null : await getUnit(name)
)
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

<template>
  <full-page :title="title">
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
            :key="connection.address.toString()"
            :name="connection.name"
          />
        </template>
        <panel
          v-for="connection in connections"
          :key="connection.address.toString()"
          class="column"
          :name="connection.name"
        >
          <item-view
            :address="connection.address"
            class="col-grow"
            kind="message"
            :title="connection.name"
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
          <panel-tab
            v-for="alerter in alerters"
            :key="alerter.address.toString()"
            :name="alerter.name"
          >
            {{ alerter.name }}
            <alerts-indicator :component-name="alerter.name" :unit-name="unit.name" />
          </panel-tab>
        </template>
        <panel
          v-for="alerter in alerters"
          :key="alerter.address.toString()"
          class="column"
          :name="alerter.name"
        >
          <item-view
            :address="alerter.address"
            class="col-grow"
            kind="alert"
            :title="alerter.name"
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
            :key="component.address.toString()"
            :name="component.name"
          >
            {{ component.name }}
          </panel-tab>
        </template>
        <panel
          v-for="component in components"
          :key="component.address.toString()"
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
          <panel-tab v-for="hud in uis" :key="hud.address.toString()" :name="hud.name" />
        </template>
        <panel v-for="ui in uis" :key="ui.address.toString()" :name="ui.name">
          <div>
            <layout :component="ui" />
          </div>
        </panel>
      </panel-group>
      <div class="q-pa-md">
        <q-markup-table v-if="components.length" bordered dense flat separator="vertical">
          <thead>
            <q-tr no-hover>
              <q-th class="self-name-column text-left">Component</q-th>
              <q-th class="text-left">Roles</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr v-for="component in components" :key="component.name" no-hover>
              <q-td class="self-name-column">{{ component.name }}</q-td>
              <q-td>{{ [...component.roles].sort().join(', ') }}</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </div>
    </div>
  </full-page>
</template>

<style lang="scss" scoped>
.self-name-column {
  max-width: 50px;
}
</style>
