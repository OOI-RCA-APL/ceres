<template>
  <div :class="classes">
    <slot />
  </div>
</template>

<script lang="ts" setup>
const { variant } = defineProps<{
  variant: 'title1' | 'title2' | 'title3' | 'body1' | 'body2'
}>()

const classes = $computed(() => `self-${variant}`)
</script>

<style lang="scss" scoped>
.self-title1 {
  font-family: 'Roboto';
  font-size: 24px;
  font-weight: 300;
  line-height: 1.5em;
}

.self-title2 {
  font-family: 'Roboto';
  font-size: 20px;
  font-weight: 300;
  line-height: 1.5em;
}

.self-title3 {
  font-family: 'Roboto';
  font-size: 18px;
  font-weight: 300;
  line-height: 1em;
}

.self-body1 {
  font-size: 16px;
  font-weight: 400;
  line-height: 1.5rem;
  letter-spacing: 0.03125em;
}

.self-body2 {
  font-size: 14px;
  font-weight: 400;
  line-height: 1.5rem;
  letter-spacing: 0.03125em;
}
</style>
