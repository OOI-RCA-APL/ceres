<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import FullPage from '@/components/FullPage.vue'
import Interface from '@/components/Interface.vue'
import ItemView from '@/components/ItemView.vue'
import Panel from '@/components/Panel.vue'
import PanelContainer from '@/components/PanelContainer.vue'
import PanelGroup from '@/components/PanelGroup.vue'
import PanelTab from '@/components/PanelTab.vue'
import Procedures from '@/components/Procedures.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useInterfaceContext } from '@/interface'

const { address = new Address('@') } = defineProps<{
  address: Address
}>()

useInterfaceContext('page/component')

const engine = useEngine()
const system = $computed(() => engine.systems.get(address))

const title = $computed(() => {
  if (address == null) {
    return 'No system selected.'
  }

  if (address.isRoot) {
    return 'Systems'
  }

  return String(address)
})

const children = $computed(() => system?.subsystems ?? [])
const systems = $computed(() => (system == null ? [] : [system, ...children]))
const executors = $computed(() => systems.filter((component) => component.procedures.length > 0))
const interfaces = $computed(() =>
  systems.filter((component) => component.roles.includes('interface'))
)

const resizablePanelProps = {
  defaultHeight: 300,
  minHeight: 114,
  maxHeight: 4000,
}
</script>

<template>
  <full-page :title>
    <template #header-append>
      <div class="items-center q-ml-sm row">
        <status-badge :address :class="$style.statusBadge" />
      </div>
    </template>
    <div v-if="system == null" class="q-pa-md">
      <q-chip>System not found.</q-chip>
    </div>
    <div v-else>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Messages"
        :persist="`components/${system.address}/messages-panel-container`"
      >
        <item-view
          :address
          class="full-height"
          :show-command-input="system.roles.includes('connection')"
          title="Messages"
          type="message"
        />
      </panel-container>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Alerts"
        :persist="`components/${system.address}/alerts-panel-container`"
      >
        <item-view :address class="full-height" title="Alerts" type="alert" />
      </panel-container>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Logs"
        :persist="`components/${system.address}/log-entries-panel-container`"
      >
        <item-view :address class="full-height" title="Logs" type="log-entry" />
      </panel-container>
      <panel-group
        v-if="executors.length"
        :panels="executors.map((current) => current.address.toString())"
        :persist="`components/${system.address}/procedures-panel-group`"
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
          <procedures class="col" :system="executor" :title="executor.address.toString()" />
        </panel>
      </panel-group>
      <panel-group
        v-if="interfaces.length"
        :panels="interfaces.map((current) => current.address.toString())"
        :persist="`components/${system.address}/interfaces-panel-group`"
        title="UI"
      >
        <template #tabs>
          <panel-tab
            v-for="ui in interfaces"
            :key="ui.address.toString()"
            :name="ui.address.toString()"
            :title="ui.address.toString() + '/ui'"
          />
        </template>
        <panel v-for="ui in interfaces" :key="ui.address.toString()" :name="ui.address.toString()">
          <div>
            <interface :address="ui.address" />
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

.statusBadge {
  margin-top: 2px;
}
</style>
