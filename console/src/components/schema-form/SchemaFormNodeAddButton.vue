<script setup lang="ts">
import icons from '@/icons'

defineEmits(['click'])
</script>

<template>
  <q-btn
    :class="$style.root"
    dense
    flat
    :icon="icons.add"
    round
    size="9px"
    @click="$emit('click')"
  />
</template>

<style lang="scss" module>
.root {
  background: transparent !important;
}

:global(.light) .root {
  color: $grey-9;
}

:global(.dark) .root {
  color: $grey-7;

  :hover {
    color: $grey-6;
  }
}
</style>
