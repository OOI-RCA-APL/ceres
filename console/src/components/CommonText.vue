<script lang="ts" setup>
defineProps<{
  variant: 'title1' | 'title2' | 'title3' | 'body1' | 'body2' | 'th' | 'description'
}>()
</script>

<template>
  <div :class="$style[variant]">
    <slot />
  </div>
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
  line-height: 1em;
}

.body1 {
  font-size: 16px;
  font-weight: 400;
  line-height: 1.5rem;
  letter-spacing: 0.03125em;
}

.body2 {
  font-size: 14px;
  font-weight: 400;
  line-height: 1.5rem;
  letter-spacing: 0.03125em;
}

.th {
  font-size: 12px;
  font-weight: 500;
}

.description {
  font-size: 11px;
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
