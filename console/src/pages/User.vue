<script lang="ts" setup>
import UserPage from '@/components/UserPage.vue'

defineProps<{
  id: string
}>()
</script>

<template>
  <UserPage :id />
</template>
