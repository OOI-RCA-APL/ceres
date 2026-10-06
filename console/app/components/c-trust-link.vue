<script lang="ts" setup>
import type { Authority } from '@/api/auth'
import icons from '@/icons'

/** A quiet link to the page for trusting the server's certificate authority, shown only when
the server manages its certificate and so has an authority to trust. */
defineProps<{
  authority: Authority | null
}>()
</script>

<template>
  <div v-if="authority != null" class="flex justify-center">
    <c-button
      class="text-muted"
      color="neutral"
      :icon="icons.trust"
      label="Trust this server?"
      size="xs"
      to="/trust"
      variant="link"
    />
  </div>
</template>
