<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { Level } from '@/api/shared'
import { usePreferences } from '@/preferences'
import { displayDuration, useTime } from '@/time'

const { address } = defineProps<{
  address: Address
}>()

const engine = useEngine()
const preferences = usePreferences()
const time = useTime()

let isShowingMenu = $ref(false)

// Everything this covers, the component itself plus everything below it. The status badge beside
// this one already covers its whole subtree, and a collapsed component reporting the status of
// what it hides while withholding its alerts is the one thing a tree like this must not do.
const scope = $computed(() => [
  address,
  ...engine.components.getDescendants(address).map((component) => component.address),
])

const severity: Record<Level, number> = {
  debug: 0,
  info: 1,
  warning: 2,
  error: 3,
  critical: 4,
}

// The worst level anything in scope reached, counted across everything that reached it. A quieter
// level underneath is left out rather than added in, since one number against one name has to mean
// the same thing here as it does on a component with nothing below it.
const info = $computed(() => {
  let worst: Level | null = null
  let count = 0
  let fromSelf = false
  let fromBelow = false

  for (const target of scope) {
    const current = engine.statistics.getLevel(target)
    if (current == null) {
      continue
    }

    const own = target.equals(address)
    if (worst == null || severity[current.level] > severity[worst]) {
      worst = current.level
      count = current.count
      fromSelf = own
      fromBelow = !own
    } else if (current.level === worst) {
      count += current.count
      fromSelf ||= own
      fromBelow ||= !own
    }
  }

  return worst == null ? null : { level: worst, count, fromSelf, fromBelow }
})

// Named for where the count came from, so it is never read as belonging to this component alone.
const subjectText = $computed(() => {
  if (info == null || !info.fromBelow) {
    return 'by this component'
  }

  return info.fromSelf ? 'by this component and those below it' : 'by components below this one'
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
