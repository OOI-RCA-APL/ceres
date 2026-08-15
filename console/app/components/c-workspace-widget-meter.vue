<script lang="ts" setup>
import { computed, onMounted } from 'vue'

import { useClient } from '@/api/client'
import { useEngine } from '@/api/engine'
import { ParticleModel } from '@/api/particles'
import type { Particle } from '@/api/particles'
import { displayDuration, useTime, utc } from '@/time'
import { useWorkspace } from '@/workspace'
import type { MeterWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MeterWidget
}>()

const client = useClient()
const engine = useEngine()
const time = useTime()
const workspace = useWorkspace()

const resolvedParticleAddress = $computed(() => workspace.resolveAddress(widget.particleAddress))

let particle = $ref<Particle | null>(null)

const value = $computed(() => {
  if (particle == null) {
    return undefined
  }

  let value: unknown
  if (widget.particleField) {
    value = particle.data[widget.particleField]
  } else {
    value = particle.data
  }

  return value
})

onMounted(async () => {
  const latest = (
    await engine.particles.getAll({
      address: resolvedParticleAddress,
      type: widget.particleType,
      order: 'timestamp:desc',
      limit: 1,
    })
  )?.[0]

  if (latest == null) {
    return
  }

  if (particle == null || utc(latest.timestamp).isAfter(particle.timestamp)) {
    particle = latest
  }
})

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

const stringified = $computed(() => {
  if (particle == null) {
    return ''
  }
  if (value === undefined) {
    return '(No Value)'
  }

  if (typeof value === 'string') {
    return value
  }

  return JSON.stringify(value)
})

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

client.useStream({
  stream: computed(() => ({
    path: '/api/particles',
    query: {
      address: resolvedParticleAddress,
      type: widget.particleType,
    },
  })),
  parse: ParticleModel,
  onReceive: (latest: Particle) => {
    if (particle == null || utc(latest.timestamp).isAfter(particle.timestamp)) {
      particle = latest
    }
  },
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
