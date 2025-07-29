<script lang="ts" setup>
import { useTheme } from '@/theme'

const theme = useTheme()
</script>

<template>
  <q-badge
    class="q-ml-sm"
    :color="theme.darklight('grey-9', 'grey-2')"
    rounded
    :text-color="theme.darklight('white', 'grey-9')"
  >
    <slot />
  </q-badge>
</template>
