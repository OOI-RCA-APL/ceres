<template>
  <q-badge v-if="levelStatistics" class="self-root" :color="color" rounded>
    {{ levelStatistics.count }}{{ levelStatistics.level[0].toUpperCase() }}
    <q-tooltip :class="`bg-${color}`">
      {{ levelStatistics.count }} {{ levelStatistics.level }} alert(s) were emitted
      {{ subjectText }} in the last hour.
    </q-tooltip>
  </q-badge>
</template>

<script lang="ts" setup>
import { useStatistics } from '@/api/queries'

const { unitName, componentName } = defineProps<{
  unitName?: string
  componentName?: string
}>()

const statistics = useStatistics()

const subjectText = $computed(() => {
  if (unitName == null) {
    return ''
  }
  if (componentName == null) {
    return 'by this unit'
  }

  return 'by this component'
})
const info = $computed(() => {
  if (statistics.data == null) {
    return null
  }
  if (unitName == null) {
    return statistics.data
  }

  const unitInfo = statistics.data.units[unitName]
  if (unitInfo == null) {
    return null
  }
  if (componentName == null) {
    return unitInfo
  }

  return unitInfo.components[componentName] ?? null
})

const levelStatistics = $computed(() => {
  const levels = info?.alerts.levels
  if (levels == null || levels.length === 0) {
    return null
  }
  return levels[levels.length - 1]
})

const color = $computed(() => {
  if (levelStatistics == null) {
    return undefined
  }

  switch (levelStatistics.level) {
    case 'debug':
      return 'grey'
    case 'info':
      return 'info'
    case 'warning':
      return 'warning'
    case 'error':
      return 'negative'
    case 'critical':
      return 'negative'
  }
})
</script>

<style lang="scss" scoped>
.self-root {
  scale: 0.8;
}
</style>
