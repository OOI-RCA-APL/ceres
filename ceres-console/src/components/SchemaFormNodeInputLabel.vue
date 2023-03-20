<template>
  <div class="row">
    <span class="q-mr-xs">{{ label }}</span>
    <span :style="{ opacity: 0.5, fontSize: undefined }"> ⸱ {{ type }}</span>
  </div>
</template>

<script lang="ts" setup>
defineProps<{
  label: string
  type: string
}>()
</script>
