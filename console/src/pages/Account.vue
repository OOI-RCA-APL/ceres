<script lang="ts" setup>
import { useAuth } from '@/auth'
import UserPage from '@/components/UserPage.vue'

const auth = useAuth()
</script>

<template>
  <UserPage :id="auth.user?.id ?? null" />
</template>
