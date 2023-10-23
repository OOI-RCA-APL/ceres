<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { useTime } from '@/time'

const time = useTime()
</script>

<template>
  <div class="items-end row">
    <common-text class="q-mr-xs" variant="title2">{{ time.now.format('H:mm') }}</common-text>
    <common-text :class="$style.timezoneIndicator" variant="body2">UTC</common-text>
  </div>
</template>

<style module>
.timezoneIndicator {
  opacity: 0.75;
}
</style>
