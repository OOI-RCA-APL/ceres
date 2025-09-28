<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import { ButtonWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ButtonWidget
}>()

const engine = useEngine()

const action = $computed(() => {
  if (widget.address == null || widget.action == null) {
    return null
  }

  return engine.components.getAction(widget.address, widget.action)
})
const label = $computed(() => {
  if (widget.label) {
    return widget.label
  }

  if (widget.action) {
    return widget.action.replace(/[\-_]+/g, ' ').toUpperCase()
  }

  return widget.name
})
</script>

<template>
  <div class="text-center">
    <q-btn
      :color="widget.color"
      :disabled="action == null"
      :flat="widget.styling === 'flat'"
      :label="label"
      no-caps
      :outline="widget.styling === 'outlined'"
    >
      <q-tooltip v-if="widget.address == null || widget.action == null">
        Button action is not configured.
      </q-tooltip>
      <q-tooltip v-else-if="action == null" class="bg-negative text-white">
        Button action {{ widget.address }}::action::{{ widget.action }} not found.
      </q-tooltip>
    </q-btn>
  </div>
</template>
