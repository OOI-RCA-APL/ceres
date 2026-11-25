<script lang="ts" setup>
import { useLatestParticle } from '@/particle-data'
import { formatParticleValue, particleFieldValue } from '@/particle-values'
import { displayDuration, useTime, utc } from '@/time'
import { useWorkspace } from '@/workspace'
import type { MeterWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MeterWidget
}>()

const time = useTime()
const workspace = useWorkspace()

const particle = $(
  useLatestParticle(() => ({
    address: workspace.resolveAddress(widget.particleAddress)?.toString() ?? null,
    type: widget.particleType ?? null,
    connection: widget.particleConnection ?? null,
  })).particle,
)

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
  <div class="relative flex min-h-full flex-1 items-center justify-center overflow-hidden">
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
