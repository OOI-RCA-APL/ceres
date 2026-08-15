<script lang="ts" setup>
import { isEqual } from 'lodash-es'

import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import type { Plain } from '@/utilities'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, schema, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { enum: Plain[] }
  path: SchemaPath
}>()

const title = $computed(() => form.getLabel(path))
const isRequired = $computed(() => form.getRequired(path))
const description = $computed(() => form.getDescription(path))

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  for (const option of schema.enum) {
    if (isEqual(option, value)) {
      return value as Plain
    }
  }

  return undefined
}

function format(value: unknown) {
  try {
    const result = JSON.stringify(value)
    if (result.startsWith('[') || result.startsWith('{')) {
      return result
    }
  } catch {
    // Fall through to the plain string form.
  }

  return String(value)
}

type Item = { label: string; value: Plain }

const items = $computed<Item[]>(() =>
  schema.enum.map((option) => ({ label: format(option), value: option })),
)

const selected = $computed<Item | undefined>(() => {
  const resolved = resolve(modelValue)
  return items.find((item) => isEqual(item.value, resolved))
})

function onClear() {
  modelValue = undefined
}
</script>

<template>
  <div>
    <div class="mb-1 flex items-baseline gap-1">
      <c-text element="span" variant="mono-sm">{{ title }}</c-text>
      <c-text class="text-muted" element="span" variant="mono-sm">
        <span class="mx-1">{{ '⸱' }}</span>
        <span>enum</span>
      </c-text>
    </div>
    <c-select-menu
      class="w-full font-mono"
      :items="items"
      :model-value="selected"
      :search-input="{ placeholder: 'Filter...' }"
      size="sm"
      :ui="{ base: 'font-mono text-xs' }"
      @update:model-value="(item: Item | undefined) => (modelValue = resolve(item?.value))"
    >
      <template #trailing>
        <c-schema-form-node-clear-button
          v-if="!isRequired && modelValue !== undefined"
          @click="onClear"
        />
      </template>
    </c-select-menu>
    <c-text v-if="description" class="mt-1 ml-3 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
