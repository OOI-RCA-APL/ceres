<script lang="ts" setup>
import type { TextVariant } from '@/api/elements'
const { element = 'div' } = defineProps<{
  variant: TextVariant
  element?: string
}>()
</script>

<template>
  <component :is="element" :class="$style[variant]">
    <slot />
  </component>
</template>

<style module>
.title1 {
  font-family: 'Roboto';
  font-size: 22px;
  font-weight: 300;
  line-height: 1.5em;
}

.title2 {
  font-family: 'Roboto';
  font-size: 18px;
  font-weight: 300;
  line-height: 1.5em;
}

.title3 {
  font-family: 'Roboto';
  font-size: 14px;
  font-weight: 300;
  line-height: 1.5em;
}

.body1 {
  font-family: 'Roboto';
  font-size: 16px;
  font-weight: 400;
  line-height: 1.5rem;
  letter-spacing: 0.03125em;
}

.body2 {
  font-family: 'Roboto';
  font-size: 14px;
  font-weight: 400;
  line-height: 1.5rem;
  letter-spacing: 0.03125em;
}

.th {
  font-family: 'Roboto';
  font-size: 12px;
  font-weight: 500;
}

.description {
  font-family: 'Roboto';
  font-size: 11px;
}

.value {
  font-family: 'Roboto';
  font-size: 18px;
  font-weight: 300;
  line-height: 1.5em;
}

:global(.light) .description {
  opacity: 0.54;
  color: black;
}

:global(.dark) .description {
  opacity: 0.7;
  color: white;
}
</style>
