<script lang="ts" setup>
import { Address } from '@/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import Interface from '@/components/Interface.vue'
import { useInterfaceContext } from '@/interface'

useInterfaceContext('page/dashboard')

const engine = useEngine()
await engine.config.suspense()

const renderer = $computed<Address | null>(() => {
  if (engine.config.console == null) {
    return null
  }

  return engine.config.console.dashboard as Address
})
</script>

<template>
  <div>
    <div class="items-center row">
      <common-text class="q-mx-md q-py-sm" variant="title2">Dashboard</common-text>
    </div>
    <q-separator />
    <div class="q-pa-sm">
      <interface v-if="renderer != null" :address="renderer" />
      <div v-else class="q-py-lg text-center" :style="{ opacity: 0.5 }">
        No dashboard component configured.
      </div>
    </div>
  </div>
</template>
