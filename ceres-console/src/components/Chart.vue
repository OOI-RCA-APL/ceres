<script setup lang="ts">
import { Option } from '@/chart'
import { useResize } from '@/resize'
import { ECharts } from 'echarts'
import Inner from 'vue-echarts'

const { loading = false, option } = defineProps<{
  autoresize?: boolean
  loading?: boolean
  option: Option
}>()

const resize = useResize()
const instance = $ref<ECharts | null>(null)

const appliedOptions: Option = $computed(() => ({
  ...option,
  backgroundColor: 'transparent',
  useUTC: true,
}))
</script>

<template>
  <inner :key="resize.key" ref="instance" :loading="loading" :option="appliedOptions" />
</template>
