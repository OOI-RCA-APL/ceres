<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import Interface from '@/components/Interface.vue'
import Panel from '@/components/Panel.vue'
import PanelGroup from '@/components/PanelGroup.vue'
import PanelTab from '@/components/PanelTab.vue'
import { useInterfaceContext } from '@/interface'
import { usePersisted } from '@/persistence'

import { computed } from 'vue'
useInterfaceContext('page/dashboard')

const engine = useEngine()
await engine.config.suspense()

const renderer = $computed(() => {
  return engine.config.console.dashboard as Address | Address[] | null
})

const persisted = usePersisted({
  schema: ({ object, array, string }) =>
    object({
      openTabs: array(string()).default(() => []),
    }),
  methods: computed(() => [
    {
      type: 'local-storage',
      key: ['page', 'dashboard'],
    },
  ]),
})
</script>

<template>
  <div>
    <div class="items-center row">
      <common-text class="q-mx-md q-py-sm" variant="title2">Dashboard</common-text>
    </div>
    <q-separator />
    <div
      v-if="renderer == null || (renderer as Address[] ?? []).length === 0"
      class="q-py-lg text-center"
      :style="{ opacity: 0.5 }"
    >
      No dashboard component configured.
    </div>
    <panel-group
      v-else-if="Array.isArray(renderer)"
      v-model="persisted.openTabs"
      :panels="renderer.map(String)"
    >
      <template #tabs>
        <panel-tab
          v-for="address in renderer"
          :key="address.toString()"
          :name="address.toString()"
        />
      </template>
      <panel v-for="address in renderer" :key="address.toString()" :name="address.toString()">
        <interface :address="address" />
      </panel>
    </panel-group>
    <div v-else class="q-ma-sm">
      <interface :address="renderer" />
    </div>
  </div>
</template>
