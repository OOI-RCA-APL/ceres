<script lang="ts" setup>
import type { Particle } from '@/api/particles'
import { highlight } from '@/utilities'

const { particle } = defineProps<{
  particle: Particle
}>()

const renderedData = $computed(() => highlight(JSON.stringify(particle.data), 'json'))
</script>

<template>
  <c-record-view-record :record="particle">
    <c-record-view-connection :address="particle.address" :name="particle.connection" />
    <c-record-view-cell class="w-0 min-w-13" name="type">
      <span class="font-mono text-[10px]">
        {{ particle.type }}
      </span>
    </c-record-view-cell>
    <c-record-view-cell name="data">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="font-mono text-[9px] whitespace-nowrap" v-html="renderedData" />
    </c-record-view-cell>
  </c-record-view-record>
</template>
