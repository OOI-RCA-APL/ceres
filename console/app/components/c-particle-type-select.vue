<script lang="ts" setup>
import { useParticleTypes } from '@/particle-types'

let modelValue = $(defineModel<string | null>({ required: true }))

const { address } = defineProps<{
  address: string | null
}>()

const types = $(useParticleTypes(() => address).types)

type Option = { label: string; value: string; description?: string }

const options = $computed<Option[]>(() =>
  types.map((type) => ({
    label: type.type,
    value: type.type,
    description: type.description ?? undefined,
  })),
)

const selected = $computed(() => {
  if (modelValue == null) {
    return undefined
  }

  // A stored type the declarations no longer carry still shows as itself.
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
    <c-text class="text-muted mb-1" variant="mono-sm">Particle Type</c-text>
    <c-select-menu
      class="w-full"
      create-item
      :items="options"
      :model-value="selected"
      placeholder="Particle Type"
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
