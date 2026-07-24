<script lang="ts" setup>
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

const scope = $computed(() => workspace.scope)

const options = $computed(() => {
  if (scope == null || showAbsolute) {
    return engine.components.all.map((component) => component.address.toString())
  }

  const base = scope.toString()
  return engine.components.all
    .filter((component) => {
      const address = component.address.toString()
      return address === base || address.startsWith(`${base}.`)
    })
    .map((component) => {
      const address = component.address.toString()
      return address === base ? '' : address.slice(base.length + 1)
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
        label="Component"
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
