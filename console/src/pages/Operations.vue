<script lang="ts" setup>
import FullPage from '@/components/FullPage.vue'
import PanelContainer from '@/components/PanelContainer.vue'
import RecordView from '@/components/RecordView.vue'
import { useInterfaceContext } from '@/interface'

useInterfaceContext('page/operations')

// const engine = useEngine()
// const persisted = usePersisted({
//   schema: ({ object, boolean }) =>
//     object({
//       isViewingMessages: boolean().default(false),
//       isViewingLogs: boolean().default(false),
//       isViewingAlerts: boolean().default(false),
//     }),
//   methods: [
//     {
//       type: 'local-storage',
//       key: ['page', 'operations'],
//     },
//   ],
// })

const title = $computed(() => {
  return `Operations`
})

// const component = $computed(() => engine.components.get(address))
// const children = $computed(() => component?.components ?? [])
// const subcomponents = $computed(() => (component == null ? [] : [component, ...children]))
// const executors = $computed(() =>
//   subcomponents.filter((component) => component.procedures.length > 0)
// )
// const interfaces = $computed(() =>
//   subcomponents.filter((component) => component.roles.includes('interface'))
// )
const resizablePanelProps = {
  defaultHeight: 300,
  minHeight: 114,
  maxHeight: 4000,
}
</script>

<template>
  <full-page :title>
    <template #header-append> </template>
    <!-- <div class="justify-center q-pt-sm row">
      <q-btn-group dense flat>
        <q-btn
          :class="$style.tabButton"
          :color="persisted.isViewingMessages ? 'primary' : undefined"
          dense
          label="Messages"
          no-caps
          @click="persisted.isViewingMessages = !persisted.isViewingMessages"
        />
        <q-btn
          :class="$style.tabButton"
          :color="persisted.isViewingLogs ? 'primary' : undefined"
          dense
          label="Logs"
          no-caps
          @click="persisted.isViewingLogs = !persisted.isViewingLogs"
        />
        <q-btn
          :class="$style.tabButton"
          :color="persisted.isViewingAlerts ? 'primary' : undefined"
          dense
          label="Alerts"
          no-caps
          @click="persisted.isViewingAlerts = !persisted.isViewingAlerts"
        />
      </q-btn-group>
    </div> -->
    <panel-container
      container-class="q-pa-sm"
      v-bind="resizablePanelProps"
      name="Messages"
      persist="messages-panel-container"
    >
      <record-view class="full-height" title="Messages" type="message" />
    </panel-container>
    <panel-container
      container-class="q-pa-sm"
      v-bind="resizablePanelProps"
      name="Alerts"
      persist="alerts-panel-container"
    >
      <record-view class="full-height" title="Alerts" type="alert" />
    </panel-container>
    <panel-container
      container-class="q-pa-sm"
      v-bind="resizablePanelProps"
      name="Logs"
      persist="logs-panel-container"
    >
      <record-view class="full-height" title="Logs" type="log-entry" />
    </panel-container>
  </full-page>
</template>

<style module>
.tabButton {
  width: 100px;
}

.addressColumn {
  max-width: 50px;
}

.statusBadge {
  margin-top: 2px;
}
</style>
