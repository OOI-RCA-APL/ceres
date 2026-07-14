<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { usePreferences } from '@/preferences'
import { displayDuration, useTime } from '@/time'

const { address } = defineProps<{
  address?: Address
}>()

const engine = useEngine()
const preferences = usePreferences()
const time = useTime()

let isShowingMenu = $ref(false)

const subjectText = $computed(() => {
  if (address == null) {
    return ''
  }

  return 'by this component'
})

const info = $computed(() => {
  if (address == null) {
    return null
  }

  return engine.statistics.getLevel(address)
})

const color = $computed(() => {
  if (info == null) {
    return undefined
  }

  switch (info.level) {
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

<template>
  <q-badge v-if="info" :class="$style.root" :color rounded>
    {{ info.count }}{{ info.level[0].toUpperCase() }}
    <q-tooltip v-if="!isShowingMenu" :class="`bg-${color}`">
      <span class="q-mr-xs">
        {{ info.count }} {{ info.level }} alert(s) were emitted {{ subjectText }} in the last
        {{ displayDuration(preferences.statisticsDuration, { hideOne: true }) }}.
      </span>
      <span v-if="engine.statistics.dataUpdatedAt" :class="$style.updatedAtText">
        Updated {{ displayDuration(time.now.diff(engine.statistics.dataUpdatedAt, 's')) }} ago.
      </span>
    </q-tooltip>
  </q-badge>
</template>

<style module>
.root {
  scale: 0.8;
}

.updatedAtText {
  opacity: 0.75;
}
</style>
