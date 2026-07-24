<script lang="ts" setup>
import { Address } from '@/api/address'
import Interface from '@/components/Interface.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import { UIWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: UIWidget
}>()

const workspace = useWorkspace()

const resolvedInterfaceAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.interfaceAddress)
  return resolved == null ? null : Address.parse(resolved)
})
</script>

<template>
  <div>
    <workspace-address-select
      :model-value="widget.interfaceAddress?.toString() ?? null"
      @update:model-value="
        (value) => (widget.interfaceAddress = value ? Address.parse(value) : null)
      "
    />
    <interface
      v-if="resolvedInterfaceAddress != null"
      :address="resolvedInterfaceAddress"
      class="q-mt-sm"
    />
  </div>
</template>
