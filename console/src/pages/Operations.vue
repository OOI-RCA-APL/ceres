<script lang="ts" setup>
import AlertView from '@/components/AlertView.vue'
import FullPage from '@/components/FullPage.vue'
import LogEntryView from '@/components/LogEntryView.vue'
import MessageView from '@/components/MessageView.vue'
import PanelContainer from '@/components/PanelContainer.vue'

const title = $computed(() => {
  return `Operations`
})

const resizablePanelProps = {
  defaultHeight: 300,
  minHeight: 114,
  maxHeight: 4000,
}
</script>

<template>
  <full-page :title>
    <panel-container
      container-class="q-pa-sm"
      v-bind="resizablePanelProps"
      name="Messages"
      persist="page/operations/messages-panel-container"
    >
      <message-view class="full-height" persist="page/operations/message-view" />
    </panel-container>
    <panel-container
      container-class="q-pa-sm"
      v-bind="resizablePanelProps"
      name="Alerts"
      persist="page/operations/alerts-panel-container"
    >
      <alert-view class="full-height" persist="alert-view" />
    </panel-container>
    <panel-container
      container-class="q-pa-sm"
      v-bind="resizablePanelProps"
      name="Logs"
      persist="page/operations/log-entry-panel-container"
    >
      <log-entry-view class="full-height" persist="page/operations/log-entry-view" />
    </panel-container>
  </full-page>
</template>
