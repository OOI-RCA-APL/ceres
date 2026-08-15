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
    <td class="w-0 min-w-13">
      <span class="font-mono text-[10px]">
        {{ particle.type }}
      </span>
    </td>
    <td>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="font-mono text-[9px] whitespace-nowrap" v-html="renderedData" />
    </td>
  </c-record-view-record>
</template>
