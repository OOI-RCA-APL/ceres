<template>
  <div ref="element"></div>
</template>

<script lang="ts" setup>
import { Chart, JSCChartConfig } from 'jscharting'
import { onBeforeUnmount, onMounted, watchEffect } from 'vue'

export type Options = JSCChartConfig

const {
  options,
  mutable = true,
  ignoreStateUpdate = false,
} = defineProps<{
  options: Options
  mutable?: boolean
  ignoreStateUpdate?: boolean
}>()

const emit = defineEmits<{
  (emit: 'rendered', chart: Chart | undefined): void
}>()

let element = $ref<Element | null>(null)
let instance = $ref<Chart | undefined>(undefined)

watchEffect(() => {
  if (instance && ignoreStateUpdate) {
    return
  }

  createChart()
})

function createChart() {
  const appliedOptions = options || {}

  // If the instance does not exist yet, create one
  if (!instance) {
    renderChart(appliedOptions)
    return
  }

  if (mutable && !(instance as any).dirty) {
    // If the mutable is true and the instance is not dirty, update the existing instance
    instance.options(appliedOptions)
  } else {
    // Create a new instance with the new values
    renderChart(appliedOptions)
  }
}

function renderChart(options: Options) {
  destroyChart()
  instance = new Chart((options.targetElement || element) as string, options, (chart) =>
    emit('rendered', chart)
  )
}

function destroyChart() {
  if (instance) {
    instance.destroy()
    instance = undefined
  }
}

onMounted(() => {
  createChart()
})

onBeforeUnmount(() => {
  destroyChart()
})
</script>
