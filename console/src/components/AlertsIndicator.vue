<script lang="ts" setup>
import { Address } from '@/address'
import { useStatistics } from '@/api/operations'
import { useSettings } from '@/settings'
import { displayDuration, useTime } from '@/time'

const { address } = defineProps<{
  address?: Address
}>()

const settings = useSettings()
const statistics = useStatistics()
const time = useTime()

let isShowingMenu = $ref(false)

const subjectText = $computed(() => {
  if (address == null || address.isRoot) {
    return ''
  }

  return 'by this component'
})

const info = $computed(() => {
  if (address == null || address.isRoot) {
    return null
  }

  return statistics.getAlertInfo(address)
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
  <q-badge v-if="info" :class="$style.root" :color="color" rounded>
    {{ info.count }}{{ info.level[0].toUpperCase() }}
    <q-tooltip v-if="!isShowingMenu" :class="`bg-${color}`">
      <span class="q-mr-xs">
        {{ info.count }} {{ info.level }} alert(s) were emitted {{ subjectText }} in the last
        {{ displayDuration(settings.statisticsDuration, { hideOne: true }) }}.
      </span>
      <span v-if="statistics.updatedAt" :class="$style.updatedAtText">
        Updated {{ displayDuration(time.now.diff(statistics.updatedAt, 's')) }} ago.
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
