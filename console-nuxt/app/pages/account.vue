<script lang="ts" setup>
import { useEngine } from '@/api/engine'

definePageMeta({ auth: true })

const engine = useEngine()
</script>

<template>
  <c-user-page :id="engine.auth.user?.id ?? null" />
</template>
