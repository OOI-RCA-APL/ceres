<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import FullPage from '@/components/FullPage.vue'
import Interface from '@/components/Interface.vue'
import Panel from '@/components/Panel.vue'
import PanelGroup from '@/components/PanelGroup.vue'
import PanelTab from '@/components/PanelTab.vue'
import { useInterfaceContext } from '@/interface'

const context = useInterfaceContext('page/dashboard')

const engine = useEngine()
await engine.config.suspense()

const renderer = $computed(() => {
  return engine.config.console.dashboard as Address | Address[] | null
})
</script>

<template>
  <full-page title="Dashboard">
    <div
      v-if="renderer == null || (renderer as Address[] ?? []).length === 0"
      class="q-py-lg text-center"
      :style="{ opacity: 0.5 }"
    >
      No dashboard component configured.
    </div>
    <panel-group
      v-else-if="Array.isArray(renderer)"
      :panels="renderer.map(String)"
      :persist="`${context.key}/panel-group`"
    >
      <template #tabs>
        <panel-tab
          v-for="address in renderer"
          :key="address.toString()"
          :name="address.toString()"
        />
      </template>
      <panel v-for="address in renderer" :key="address.toString()" :name="address.toString()">
        <interface :address />
      </panel>
    </panel-group>
    <div v-else class="q-ma-sm">
      <interface :address="renderer" />
    </div>
  </full-page>
</template>
