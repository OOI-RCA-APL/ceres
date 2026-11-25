<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import { useLatestParticle } from '@/particle-data'
import { connectionLabel } from '@/particle-types'
import { formatParticleValue, particleFieldValue } from '@/particle-values'
import { displayDuration, useTime, utc } from '@/time'
import { useWorkspace } from '@/workspace'
import type { MeterWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MeterWidget
}>()

const engine = useEngine()
const time = useTime()
const workspace = useWorkspace()

const address = $computed(
  () => workspace.resolveAddress(widget.particleAddress)?.toString() ?? null,
)

/** A connection chosen from the prompt by someone who cannot edit the workspace, which holds for
this view alone. */
let chosen = $ref<string | null>(null)

const connection = $computed(() => widget.particleConnection ?? chosen)

/** The connections the type is known to carry, from its declaration and from the records this
meter has seen, since an unnarrowed meter learns of a second one only when it arrives. */
const declared = $computed(() => {
  if (address == null || widget.particleType == null) {
    return []
  }

  return (
    engine.components.get(address)?.particles.find((type) => type.type === widget.particleType)
      ?.connections ?? []
  )
})

let seen = $ref<string[]>([])

const particle = $(
  useLatestParticle(() => ({
    address,
    type: widget.particleType ?? null,
    connection,
  })).particle,
)

watch(
  () => [address, widget.particleType, connection],
  () => (seen = []),
)

watch(
  () => particle?.connection,
  (name) => {
    if (connection == null && name != null && !seen.includes(name)) {
      seen = [...seen, name]
    }
  },
)

/** The connections to choose between, set only while the meter would blend several. */
const choices = $computed(() => {
  if (connection != null) {
    return []
  }

  const names = [...new Set([...declared, ...seen])]
  return names.length > 1 ? names : []
})

function choose(name: string) {
  if (workspace.canEdit) {
    widget.particleConnection = name
  } else {
    chosen = name
  }
}

const textWeight = $computed(() => {
  switch (widget.fontWeight) {
    case 'slim':
      return 200
    case 'normal':
      return 300
    case 'bold':
      return 'bold'
    default:
      return 400
  }
})

const textStyle = $computed(() => {
  const fontSize = Math.max(Math.min(widget.fontSize ?? 18, 60), 0)
  return {
    fontSize: `${fontSize}px`,
    fontWeight: textWeight,
  }
})

const stringified = $computed(() =>
  particle == null
    ? ''
    : formatParticleValue(particleFieldValue(particle, widget.particleField), widget.decimals),
)

const display = $computed(() => {
  let current = stringified
  if (current.trim() === '') {
    return ' '
  }

  if (widget.prefix) {
    current = `${widget.prefix}${current}`
  }
  if (widget.suffix) {
    current = `${current}${widget.suffix}`
  }

  return current
})

const updatedAt = $computed(() => {
  if (particle == null) {
    return ''
  }

  const timestamp = utc(particle.timestamp)
  const age = time.nowFast.diff(timestamp, 'second')
  if (age < 1.5) {
    return 'Now'
  }

  return `${displayDuration(age, { decimals: 0, short: true })} ago`
})
</script>

<template>
  <!-- A value blended from several sources would mislead, so the meter asks which to show. -->
  <div
    v-if="choices.length > 0"
    class="flex min-h-full flex-1 flex-col items-center justify-center gap-2 p-2"
  >
    <c-text variant="description">Choose a connection</c-text>
    <div class="flex flex-wrap justify-center gap-1">
      <c-button
        v-for="name in choices"
        :key="name"
        color="neutral"
        :label="address == null ? name : connectionLabel(engine, address, name)"
        size="xs"
        variant="outline"
        @click="choose(name)"
      />
    </div>
  </div>
  <div v-else class="relative flex min-h-full flex-1 items-center justify-center overflow-hidden">
    <div class="text-center">
      <div class="m-0 p-0 font-extralight whitespace-pre-wrap" :style="textStyle">
        {{ display }}
      </div>
      <div class="absolute right-1 bottom-0.5 text-[10px] opacity-50">
        {{ updatedAt }}
      </div>
    </div>
  </div>
</template>
