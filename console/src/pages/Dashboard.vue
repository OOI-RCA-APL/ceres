<script lang="ts" setup>
import { getComponent, useConfig, useQuery } from '@/api/operations'
import CommonText from '@/components/CommonText.vue'
import Interface from '@/components/Interface.vue'

const config = useConfig()

const rendererQuery = useQuery('dashboard-renderer', async () => {
  if (config.data?.server?.console?.dashboard?.render == null) {
    return null
  }

  return await getComponent(config.data.server.console.dashboard.render)
})
await rendererQuery.suspense()

const renderer = $computed(() => rendererQuery.data?.value ?? null)
</script>

<template>
  <div>
    <div class="items-center row">
      <common-text class="q-mx-md q-py-sm" variant="title2">Dashboard</common-text>
    </div>
    <q-separator />
    <div class="q-pa-sm">
      <interface v-if="renderer != null" :component="renderer" />
    </div>
  </div>
</template>
