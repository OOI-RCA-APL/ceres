<script lang="ts" setup>
import { Address } from '@/address'
import { getComponent } from '@/api/operations'
import ComponentProcedures from '@/components/ComponentProcedures.vue'
import FullPage from '@/components/FullPage.vue'
import ItemView from '@/components/ItemView.vue'
import Layout from '@/components/Layout.vue'
import Panel from '@/components/Panel.vue'
import PanelContainer from '@/components/PanelContainer.vue'
import PanelGroup from '@/components/PanelGroup.vue'
import PanelTab from '@/components/PanelTab.vue'
import { computed } from 'vue'
import { useQuery } from 'vue-query'

const { address = new Address('@') } = defineProps<{
  address: Address
}>()

const query = useQuery(['getComponent', computed(() => address)], async () =>
  address == null ? null : await getComponent(address)
)
await query.suspense()

const component = $computed(() => query.data?.value ?? null)

const title = $computed(() => {
  if (address == null) {
    return 'No component selected.'
  }

  if (address.isRoot) {
    return 'Components'
  }

  return String(address)
})

const children = $computed(() => component?.components ?? [])
const components = $computed(() => (component == null ? [] : [component, ...children]))
const executors = $computed(() => components.filter((component) => component.procedures.length > 0))
const uis = $computed(() => components.filter((component) => component.roles.includes('ui')))

const resizablePanelProps = {
  defaultHeight: 300,
  minHeight: 114,
  maxHeight: 4000,
}
</script>

<template>
  <full-page :title="title">
    <div v-if="component == null" class="q-pa-md">
      <q-chip>Component not found.</q-chip>
    </div>
    <div v-else>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Messages"
        :persist="`components/${component.address}/messages-panel-container`"
      >
        <item-view :address="address" class="full-height" kind="message" title="Messages" />
      </panel-container>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Alerts"
        :persist="`components/${component.address}/alerts-panel-container`"
      >
        <item-view :address="address" class="full-height" kind="alert" title="Alerts" />
      </panel-container>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Logs"
        :persist="`components/${component.address}/log-entries-panel-container`"
      >
        <item-view :address="address" class="full-height" kind="log-entry" title="Logs" />
      </panel-container>
      <panel-group
        v-if="executors.length"
        :panels="executors.map((current) => current.address.toString())"
        :persist="`components/${component.address}/procedures-panel-group`"
        title="Procedures"
      >
        <template #tabs>
          <panel-tab
            v-for="executor in executors"
            :key="executor.address.toString()"
            :name="executor.address.toString()"
            :title="executor.address.toString() + '/procedures'"
          />
        </template>
        <panel
          v-for="executor in executors"
          :key="executor.address.toString()"
          class="column"
          :name="executor.address.toString()"
        >
          <component-procedures
            class="col"
            :component="executor"
            :title="executor.address.toString()"
          />
        </panel>
      </panel-group>
      <panel-group
        v-if="uis.length"
        :panels="uis.map((current) => current.address.toString())"
        :persist="`components/${component.address}/displays-panel-group`"
        title="UI"
      >
        <template #tabs>
          <panel-tab
            v-for="hud in uis"
            :key="hud.address.toString()"
            :name="hud.address.toString()"
            :title="hud.address.toString() + '/ui'"
          />
        </template>
        <panel v-for="ui in uis" :key="ui.address.toString()" :name="ui.address.toString()">
          <div>
            <layout :component="ui" />
          </div>
        </panel>
      </panel-group>
    </div>
  </full-page>
</template>

<style module>
.addressColumn {
  max-width: 50px;
}
</style>
