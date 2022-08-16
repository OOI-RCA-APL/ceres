<template>
  <div>
    <div class="items-center row">
      <common-text class="q-ml-md q-my-xs" variant="title2">{{ title }}</common-text>
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
