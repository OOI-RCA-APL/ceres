<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

defineProps<{
  title: string
}>()
</script>

<template>
  <q-card bordered :class="$style.card" flat>
    <div class="q-mx-md q-my-sm">
      <common-text element="h2" variant="title2">{{ title }}</common-text>
    </div>
    <q-separator />
    <slot />
  </q-card>
</template>

<style lang="scss" module>
.card {
  margin-top: 16px;
  max-width: 440px;
  width: 100%;
}
</style>
