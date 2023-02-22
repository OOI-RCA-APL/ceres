<template>
  <div class="full-height self-root">
    <div class="items-center row self-header">
      <common-text class="q-ml-md q-py-sm" variant="title2">{{ title }}</common-text>
      <slot name="header-append" />
    </div>
    <q-separator />
    <slot />
  </div>
</template>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

defineProps<{
  title: string
}>()
</script>

<style lang="scss" scoped>
.body--light .self-root {
  background-color: $grey-2;
}

.body--light .self-header {
  background-color: white;
}
</style>
