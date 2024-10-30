<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import Interface from '@/components/Interface.vue'
import { UIWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: UIWidget
}>()

const engine = useEngine()
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
      v-if="widget.interfaceAddress != null"
      :address="widget.interfaceAddress"
      class="q-mt-sm"
    />
  </div>
</template>
