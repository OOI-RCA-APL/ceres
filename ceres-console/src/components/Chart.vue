<template>
  <inner
    :key="resize.key"
    ref="instance"
    :autoresize="autoresize"
    :loading="loading"
    :option="appliedOptions"
  />
</template>

<script setup lang="ts">
import { Option } from '@/chart'
import { useResize } from '@/resize'
import { ECharts } from 'echarts'
import { watch } from 'vue'
import Inner from 'vue-echarts'

const {
  autoresize = true,
  loading = false,
  option,
} = defineProps<{
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

watch(resize, () => {
  instance?.resize()
})
</script>
