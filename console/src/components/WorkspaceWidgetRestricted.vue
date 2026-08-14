<script lang="ts" setup>
import { useAuth } from '@/api/auth'
import icons from '@/icons'
import { Widget } from '@/workspace'

defineProps<{ widget: Widget }>()

const auth = useAuth()
</script>

<template>
  <div class="column full-height items-center justify-center text-grey-6">
    <q-icon :name="icons.locked" size="24px" />
    <div class="q-mt-sm text-caption">
      {{ auth.user == null ? 'Sign in to see this.' : "Requires permissions you don't have." }}
    </div>
  </div>
</template>
