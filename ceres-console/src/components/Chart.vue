<template>
  <inner :autoresize="autoresize" :loading="loading" :option="appliedOptions" />
</template>

<script setup lang="ts">
import { Option } from '@/chart'
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

const appliedOptions: Option = $computed(() => ({
  ...option,
  backgroundColor: 'transparent',
  useUTC: true,
}))
</script>
