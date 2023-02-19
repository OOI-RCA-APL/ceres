<template>
  <div :class="!$q.dark.isActive && 'bg-grey-2'">
    <div :class="[!$q.dark.isActive && 'bg-white', 'items-center position-sticky row']">
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
