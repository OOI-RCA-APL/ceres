<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

defineProps<{
  title: string
}>()
</script>

<template>
  <div class="self-full-page-root">
    <div class="items-center row self-full-page-header">
      <common-text class="q-ml-md q-py-sm" variant="title2">{{ title }}</common-text>
      <slot name="header-append" />
    </div>
    <q-separator />
    <slot />
  </div>
</template>

<style lang="scss" scoped>
.body--light .self-full-page-root {
  background-color: $grey-2;
}

.body--light .self-full-page-header {
  background-color: white;
}
</style>
