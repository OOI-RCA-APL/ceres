<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import UserPage from '@/components/UserPage.vue'

const engine = useEngine()
</script>

<template>
  <UserPage :id="engine.auth.user?.id ?? null" />
</template>
