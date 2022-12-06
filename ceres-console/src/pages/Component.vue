<template>
  <full-page :title="title">
    <template #header-append>
      <q-chip
        v-if="componentConfig?.kind === 'connection'"
        class="q-ml-xs text-capitalize"
        :color="(componentConfig as any)['state'] === 'connected' ? 'positive' : 'warning'"
        dense
        text-color="white"
      >
        Connected
      </q-chip>
      <q-space />
      <unit-controls v-if="unitConfig" class="q-mr-md" :unit-name="unitName" />
    </template>
    <div v-if="unitConfig && componentConfig?.kind === 'connection'" class="q-pa-md">
      <section-card class="q-mb-sm" padding title="Info">
        <q-markup-table bordered class="q-mb-sm" dense flat separator="vertical">
          <thead>
            <q-tr no-hover>
              <q-th class="text-left">Target</q-th>
              <q-th class="text-left">Connected At</q-th>
            </q-tr>
          </thead>
          <tbody>
            <q-tr no-hover>
              <q-td>(TARGET)</q-td>
              <q-td>(CONNECTED AT)</q-td>
            </q-tr>
          </tbody>
        </q-markup-table>
      </section-card>
      <message-view
        :component-name="componentName"
        container-class="component-page-message-view-container"
        title="Messages"
        :unit-name="unitName"
      />
    </div>
    <div v-if="componentInfo.displays.length" class="q-pa-md">
      <display
        v-for="display in componentInfo.displays"
        :key="display.name"
        class="q-mb-sm"
        :component-name="componentName"
        :display-name="display.name"
        :unit-name="unitName"
      />
    </div>
  </full-page>
</template>

<script lang="ts" setup>
import { getComponent, useConfig } from '@/api/queries'
import Display from '@/components/Display.vue'
import FullPage from '@/components/FullPage.vue'
import MessageView from '@/components/MessageView.vue'
import SectionCard from '@/components/SectionCard.vue'
import UnitControls from '@/components/UnitControls.vue'

const { unitName, componentName } = defineProps<{
  unitName: string
  componentName: string
}>()

const config = useConfig()
const unitConfig = $computed(() => config.getUnit(unitName))
const componentConfig = $computed(() => config.getComponent(unitName, componentName))

const componentInfo = await getComponent(unitName, componentName)

const title = $computed(() => {
  if (unitConfig == null) {
    return `Unit "${unitName}" does not exist.`
  }

  if (componentConfig == null) {
    return `Connection "${componentName}" does not exist.`
  }

  return `@${unitName}.${componentName}`
})
</script>

<style lang="scss">
.component-page-message-view-container {
  height: 400px;
}
</style>
