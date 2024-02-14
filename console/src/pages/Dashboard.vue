<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import Interface from '@/components/Interface.vue'
import { useInterfaceContext } from '@/interface'
import { useStore } from '@/store'

useInterfaceContext('page/dashboard')

const store = useStore()

const renderer = $computed(() => {
  if (store.config?.dashboard == null) {
    return null
  }

  return store.config.dashboard
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
