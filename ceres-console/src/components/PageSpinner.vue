<template>
  <div class="full-width items-center justify-center q-pb-lg self-container window-height">
    <spinner class="self-spinner" color="primary" size="75px" />
  </div>
</template>

<script lang="ts" setup>
import Spinner from '@/components/Spinner.vue'
</script>

<style lang="scss" scoped>
.self-container {
  align-items: center;
  display: flex;
  justify-content: center;
  padding-bottom: 50vh;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
