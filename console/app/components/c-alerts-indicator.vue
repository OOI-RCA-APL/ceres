<script lang="ts" setup>
import type { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import type { Level } from '@/api/shared'
import { usePreferences } from '@/preferences'
import { displayDuration, useTime } from '@/time'

const { address } = defineProps<{
  address: Address
}>()

const engine = useEngine()
const preferences = usePreferences()
const time = useTime()

// The component itself plus everything below it, matching the subtree the status badge covers.
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

// The worst level anything in scope reached, counted across everything that reached it. Quieter
// levels are excluded so the number means the same as on a component with nothing below it.
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

// Says where the count came from since it may include components below this one.
const subjectText = $computed(() => {
  if (info == null || !info.fromBelow) {
    return 'by this component'
  }

  return info.fromSelf ? 'by this component and those below it' : 'by components below this one'
})

const color = $computed(() => {
  switch (info?.level) {
    case 'debug':
      return 'neutral'
    case 'info':
      return 'info'
    case 'warning':
      return 'warning'
    case 'error':
    case 'critical':
      return 'error'
    default:
      return 'neutral'
  }
})

const tooltip = $computed(() => {
  if (info == null) {
    return ''
  }

  const window = displayDuration(preferences.statisticsDuration, { hideOne: true })
  const emitted =
    `${info.count} ${info.level} alert(s) were emitted ${subjectText} ` + `in the last ${window}.`
  if (!engine.statistics.dataUpdatedAt) {
    return emitted
  }

  const age = displayDuration(time.now.diff(engine.statistics.dataUpdatedAt, 's'))
  return `${emitted} Updated ${age} ago.`
})
</script>

<template>
  <c-tooltip v-if="info != null" :text="tooltip">
    <c-badge class="scale-80" :color="color" size="sm" variant="subtle">
      {{ info.count }}{{ info.level[0]!.toUpperCase() }}
    </c-badge>
  </c-tooltip>
</template>
