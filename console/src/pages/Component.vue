<script lang="ts" setup>
import { Address } from '@/address'
import { getComponent } from '@/api/operations'
import ComponentProcedures from '@/components/ComponentProcedures.vue'
import ComponentStatusBadge from '@/components/ComponentStatusBadge.vue'
import FullPage from '@/components/FullPage.vue'
import Interface from '@/components/Interface.vue'
import ItemView from '@/components/ItemView.vue'
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
const interfaces = $computed(() =>
  components.filter((component) => component.roles.includes('interface'))
)

const resizablePanelProps = {
  defaultHeight: 300,
  minHeight: 114,
  maxHeight: 4000,
}
</script>

<template>
  <full-page :title="title">
    <template #header-append>
      <div class="items-center q-ml-sm row">
        <component-status-badge :address="address" :class="$style.statusBadge" />
      </div>
    </template>
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
        <item-view
          :address="address"
          class="full-height"
          :show-command-input="component.roles.includes('connection')"
          title="Messages"
          type="message"
        />
      </panel-container>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Alerts"
        :persist="`components/${component.address}/alerts-panel-container`"
      >
        <item-view :address="address" class="full-height" title="Alerts" type="alert" />
      </panel-container>
      <panel-container
        container-class="q-pa-sm"
        v-bind="resizablePanelProps"
        name="Logs"
        :persist="`components/${component.address}/log-entries-panel-container`"
      >
        <item-view :address="address" class="full-height" title="Logs" type="log-entry" />
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
        v-if="interfaces.length"
        :panels="interfaces.map((current) => current.address.toString())"
        :persist="`components/${component.address}/interfaces-panel-group`"
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
            <interface :component="ui" />
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
