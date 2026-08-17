<script lang="ts" setup>
import { useAuth } from '@/api/auth'
import icons from '@/icons'
import type { Widget } from '@/workspace'

defineProps<{ widget: Widget }>()

const auth = useAuth()
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center text-muted">
    <c-icon :name="icons.locked" size="24" />
    <c-text class="mt-2" variant="description">
      {{ auth.user == null ? 'Sign in to see this.' : "Requires permissions you don't have." }}
    </c-text>
  </div>
</template>
