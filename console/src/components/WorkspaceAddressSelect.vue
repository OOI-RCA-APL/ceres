<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import { useWorkspace } from '@/workspace'

const { modelValue, selector = false } = defineProps<{
  modelValue: string | null
  selector?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

const engine = useEngine()
const workspace = useWorkspace()

// A value is absolute when it names a full address. The toggle only controls which options
// are offered, the stored string carries the choice.
let showAbsolute = $ref(modelValue != null && modelValue.startsWith('@'))

// Keep the toggle in sync when the stored value changes out from under us, such as when this
// component is reused across rows with different particles in the chart settings editor. A
// null value does not disagree with either toggle state, so it never overrides an explicit
// user choice.
watch(
  () => modelValue,
  (value) => {
    if (value == null) {
      return
    }

    const isAbsolute = value.startsWith('@')
    if (isAbsolute !== showAbsolute) {
      showAbsolute = isAbsolute
    }
  }
)

const scope = $computed(() => workspace.scope)

type Option = { label: string; value: string }

const options = $computed<Option[]>(() => {
  if (scope == null || showAbsolute) {
    return engine.components.all.map((component) => {
      const address = component.address.toString()
      return { label: address, value: address }
    })
  }

  const base = scope.toString()
  return engine.components.all
    .filter((component) => {
      const address = component.address.toString()
      return address === base || address.startsWith(`${base}.`)
    })
    .map((component) => {
      const address = component.address.toString()
      if (address === base) {
        // The scope root itself has no relative path, so represent it with its absolute
        // address instead of an empty string, which cannot round-trip through the adopters'
        // falsy checks or `Address.parse`.
        return { label: '(this component)', value: address }
      }

      return { label: address.slice(base.length + 1), value: address.slice(base.length + 1) }
    })
})

function update(value: string | null) {
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="items-center q-col-gutter-sm row">
    <div class="col-grow">
      <q-select
        clearable
        dense
        emit-value
        label="Component"
        map-options
        :model-value="modelValue"
        :options="options"
        options-dense
        outlined
        @update:model-value="update"
      />
    </div>
    <div v-if="scope != null" class="col-auto">
      <q-toggle v-model="showAbsolute" dense label="Absolute" size="sm" />
    </div>
  </div>
</template>
