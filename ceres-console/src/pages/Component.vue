<script lang="ts" setup>
import { Address } from '@/address'
import { getComponent } from '@/api/operations'
import ComponentProcedures from '@/components/ComponentProcedures.vue'
import FullPage from '@/components/FullPage.vue'
import ItemView from '@/components/ItemView.vue'
import Layout from '@/components/Layout.vue'
import Panel from '@/components/Panel.vue'
import PanelGroup from '@/components/PanelGroup.vue'
import PanelTab from '@/components/PanelTab.vue'
import { computed } from 'vue'
import { useQuery } from 'vue-query'

const { address = null } = defineProps<{
  address?: Address | null
}>()

const query = useQuery(['getComponent', computed(() => address)], async () =>
  address == null ? null : await getComponent(address)
)
await query.suspense()
console.log(JSON.stringify(query.data.value))

const component = $computed(() => query.data?.value ?? null)

const title = $computed(() => {
  if (address == null) {
    return 'No component selected.'
  }

  return String(address)
})

const components = $computed(() => component?.components ?? [])
const connections = $computed(() =>
  components.filter((component) => component.roles.includes('connection'))
)
const alerters = $computed(() =>
  components.filter((component) => component.roles.includes('alerter'))
)
const executors = $computed(() => components.filter((component) => component.procedures.length > 0))
const uis = $computed(() => components.filter((component) => component.roles.includes('ui')))
</script>

<template>
  <full-page :title="title">
    <div v-if="components.length === 0" class="q-pa-md">
      <q-chip>No configuration found.</q-chip>
    </div>
    <div v-else-if="component">
      <panel-group
        v-if="connections.length"
        :default-height="300"
        :panels="connections.map((current) => current.name)"
        :persist="`components/${component.address}/messages-panel-group`"
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
        :persist="`components/${component.address}/alert-panel-group`"
        title="Alerts"
      >
        <template #tabs>
          <panel-tab
            v-for="alerter in alerters"
            :key="alerter.address.toString()"
            :name="alerter.name"
          >
            <template #append>
              <!-- <alerts-indicator
                :component-name="alerter.name"
                :title="alerter.name"
                :unit-name="unit.name"
              /> -->
            </template>
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
        :default-height="300"
        :panels="components.map((current) => current.name)"
        :persist="`components/${component.address}/log-entry-panel-group`"
        title="Logs"
      >
        <template #tabs>
          <panel-tab
            v-for="component in components"
            :key="component.address.toString()"
            :name="component.name"
          />
        </template>
        <panel
          v-for="component in components"
          :key="component.address.toString()"
          class="column"
          :name="component.name"
        >
          <item-view
            :address="component.address"
            class="col-grow"
            kind="log-entry"
            :title="component.name"
          />
        </panel>
      </panel-group>
      <panel-group
        v-if="executors.length"
        :panels="executors.map((current) => current.name)"
        :persist="`components/${component.address}/procedures-panel-group`"
        title="Procedures"
      >
        <template #tabs>
          <panel-tab
            v-for="executor in executors"
            :key="executor.address.toString()"
            :name="executor.name"
          >
            {{ executor.name }}
          </panel-tab>
        </template>
        <panel
          v-for="executor in executors"
          :key="executor.address.toString()"
          class="column"
          :name="executor.name"
        >
          <component-procedures class="col" :component="executor" :title="executor.name" />
        </panel>
      </panel-group>
      <panel-group
        v-if="uis.length"
        :panels="uis.map((current) => current.name)"
        :persist="`components/${component.address}/displays-panel-group`"
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
              <q-th :class="[$style.nameColumn, 'text-left']">Component</q-th>
              <q-th class="text-left">Roles</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr v-for="component in components" :key="component.name" no-hover>
              <q-td :class="$style.nameColumn">{{ component.name }}</q-td>
              <q-td>{{ [...component.roles].sort().join(', ') }}</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </div>
    </div>
  </full-page>
</template>

<style module>
.nameColumn {
  max-width: 50px;
}
</style>
