<script lang="ts" setup>
import moment from 'moment'
import { computed, onMounted } from 'vue'

import { useClient } from '@/api/client'
import { useEngine } from '@/api/engine'
import { Particle, ParticleModel } from '@/api/particles'
import { displayDuration, useTime } from '@/time'
import { ValueWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: ValueWidget
}>()

const client = useClient()
const engine = useEngine()
const time = useTime()

let particle = $ref<Particle | null>(null)

let value = $computed(() => {
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
      address: widget.particleAddress,
      type: widget.particleType,
      order: 'timestamp:desc',
      limit: 1,
    })
  )?.[0]

  if (latest == null) {
    return
  }

  if (particle == null || moment.utc(latest.timestamp).isAfter(particle.timestamp)) {
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

  let timestamp = moment.utc(particle.timestamp)
  let age = time.nowFast.diff(timestamp, 'seconds')
  if (age < 1.5) {
    return 'Now'
  }

  return `${displayDuration(age, { decimals: 0, short: true })} ago`
})

client.useStream({
  stream: computed(() => ({
    path: '/api/particles',
    query: {
      address: widget.particleAddress,
      type: widget.particleType,
    },
  })),
  parse: ParticleModel as any,
  onReceive: (latest: Particle) => {
    if (particle == null || moment.utc(latest.timestamp).isAfter(particle.timestamp)) {
      particle = latest
    }
  },
})
</script>

<template>
  <div :class="$style.root">
    <div class="text-center">
      <div :class="$style.text" :style="textStyle">{{ display }}</div>
      <div :class="$style.updatedAt">
        {{ updatedAt }}
      </div>
    </div>
  </div>
</template>

<style lang="scss" module>
.root {
  display: flex;
  flex: 1;
  overflow: hidden;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  position: relative;
}

.text {
  font-weight: 200;
  padding: 0;
  margin: 0;
  white-space: pre-wrap;
}

.updatedAt {
  opacity: 0.5;
  font-size: 10px;
  position: absolute;
  bottom: 2px;
  right: 4px;
}
</style>
