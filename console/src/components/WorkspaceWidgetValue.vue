<script lang="ts" setup>
import { computed } from 'vue'

import { useClient } from '@/api/client'
import { Particle, ParticleModel } from '@/api/particles'
import { ValueWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: ValueWidget
}>()

const client = useClient()

let hasValue = $ref(false)
let value = $ref<any>(undefined)

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
  if (!hasValue) {
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
    return ''
  }

  if (widget.prefix) {
    current = `${widget.prefix}${current}`
  }
  if (widget.suffix) {
    current = `${current}${widget.suffix}`
  }

  return current
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
  onReceive: (particle: Particle) => {
    hasValue = true
    const current = particle.data
    if (widget.particleField) {
      value = current[widget.particleField]
    } else {
      value = current
    }
  },
})
</script>

<template>
  <div :class="$style.root">
    <div :class="$style.text" :style="textStyle">{{ display }}</div>
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
}

.text {
  font-weight: 200;
  padding: 0;
  margin: 0;
}
</style>
