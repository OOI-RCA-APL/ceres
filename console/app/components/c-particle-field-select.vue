<script lang="ts" setup>
import { describeFieldType, isPlottableField, useParticleTypes } from '@/particle-types'
import type { Schema } from '@/schema-form'

let modelValue = $(defineModel<string | null>({ required: true }))

const { address, particleType } = defineProps<{
  address: string | null
  particleType: string | null
}>()

const types = $(useParticleTypes(() => address).types)

const selectedType = $computed(() => types.find((type) => type.type === particleType) ?? null)

// Fields that can plot lead the list since those are the ones worth reaching for first.
const fields = $computed(() => {
  const fields = selectedType?.fields ?? []
  const plottable = fields.filter((field) => isPlottableField(field.schema as Schema))
  const rest = fields.filter((field) => !isPlottableField(field.schema as Schema))
  return [...plottable, ...rest]
})

type Option = { label: string; value: string; typeLabel?: string; description?: string }

const options = $computed<Option[]>(() =>
  fields.map((field) => {
    const schema = field.schema as Schema
    const title = typeof schema === 'object' ? schema.title : undefined
    const description = typeof schema === 'object' ? schema.description : undefined

    return {
      label: title ?? field.name,
      value: field.name,
      typeLabel: describeFieldType(schema),
      description,
    }
  }),
)

const selected = $computed(() => {
  if (modelValue == null) {
    return undefined
  }

  // A stored field the declarations no longer carry still shows as itself.
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
    <c-text class="text-muted mb-1" variant="mono-sm">Field</c-text>
    <c-select-menu
      class="w-full"
      create-item
      :items="options"
      :model-value="selected"
      placeholder="Field"
      :search-input="{ placeholder: 'Filter...' }"
      size="sm"
      @create="onCreate"
      @update:model-value="(option?: Option) => (modelValue = option?.value ?? null)"
    >
      <template #item-label="{ item }">
        <div>
          <div>{{ item.label }}</div>
          <c-text v-if="item.typeLabel" variant="description">
            <span class="font-mono">{{ item.typeLabel }}</span>
            <span v-if="item.description"> &middot; {{ item.description }}</span>
          </c-text>
        </div>
      </template>
    </c-select-menu>
  </div>
</template>
