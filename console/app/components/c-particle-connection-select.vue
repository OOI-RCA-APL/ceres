<script lang="ts" setup>
import { useEngine } from '@/api/engine'

let modelValue = $(defineModel<string | null>({ required: true }))

const { address, particleType = null } = defineProps<{
  address: string | null

  /** Narrows the list to the connections this type declares, where it declares any. */
  particleType?: string | null
}>()

const engine = useEngine()

type Option = { label: string; value: string; description?: string }

const options = $computed<Option[]>(() => {
  const component = address == null ? null : engine.components.get(address)
  const connections = component?.connections ?? []

  // The declared connections are the ones the type's records carry, so a type declaring any
  // narrows the list to them. An unattributed type keeps the component's whole list.
  const declared = component?.particles.find((type) => type.type === particleType)?.connections
  const shown =
    declared != null && declared.length > 0
      ? connections.filter((connection) => declared.includes(connection.name))
      : connections

  return shown.map((connection) => ({
    label: connection.name,
    value: connection.name,
    description: connection.label ?? undefined,
  }))
})

const selected = $computed(() => {
  if (modelValue == null) {
    return undefined
  }

  // A stored connection the component no longer declares still shows as itself.
  return (
    options.find((option) => option.value === modelValue) ?? {
      label: modelValue,
      value: modelValue,
    }
  )
})

function onCreate(label: string) {
  modelValue = label
}
</script>

<template>
  <div>
    <c-text class="text-muted mb-1" variant="mono-sm">Connection</c-text>
    <c-select-menu
      class="w-full"
      create-item
      :items="options"
      :model-value="selected"
      placeholder="Every Connection"
      :search-input="{ placeholder: 'Filter...' }"
      size="sm"
      @create="onCreate"
      @update:model-value="(option?: Option) => (modelValue = option?.value ?? null)"
    >
      <template #item-label="{ item }">
        <div>
          <div>{{ item.label }}</div>
          <c-text v-if="item.description" variant="description">{{ item.description }}</c-text>
        </div>
      </template>
    </c-select-menu>
  </div>
</template>
