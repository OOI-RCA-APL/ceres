<template>
  <inner :autoresize="autoresize" :loading="loading" :option="appliedOptions" />
</template>

<script setup lang="ts">
import Inner from 'vue-echarts'
import { Option } from '../chart'

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
