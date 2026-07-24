<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import Interface from '@/components/Interface.vue'
import { UIWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: UIWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedInterfaceAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.interfaceAddress)
  return resolved == null ? null : Address.parse(resolved)
})
</script>

<template>
  <div>
    <q-select
      v-model="widget.interfaceAddress"
      dense
      filled
      label="Component"
      :options="
        engine.components.all
          .filter((current) => current.roles.includes('interface'))
          .map((current) => current.address.toString())
      "
      options-dense
    />
    <interface
      v-if="resolvedInterfaceAddress != null"
      :address="resolvedInterfaceAddress"
      class="q-mt-sm"
    />
  </div>
</template>
