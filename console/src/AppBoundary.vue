<script lang="ts" setup>
import { useQuasar } from 'quasar'
import { onErrorCaptured } from 'vue'

const quasar = useQuasar()

onErrorCaptured((error) => {
  console.error(error)
  quasar.notify({
    message: 'An unexpected error occurred. You may need to refresh the page.',
    color: 'negative',
    group: 'unexpected',
    position: 'bottom',
    timeout: 10000,
    badgeStyle: {
      display: 'none',
    },
  })

  return false
})
</script>

<template>
  <slot />
</template>
