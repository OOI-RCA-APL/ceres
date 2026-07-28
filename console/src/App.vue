<script lang="ts" setup>
import AppBoundary from '@/AppBoundary.vue'
import AppLoader from '@/AppLoader.vue'
import '@/modifiers'
</script>

<template>
  <app-boundary>
    <suspense>
      <app-loader />
    </suspense>
  </app-boundary>
</template>
