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
  <div :class="form.embedded && 'contents'">
    <div v-if="!form.embedded" class="mb-1 flex items-baseline gap-1">
      <c-text inline variant="mono-sm">{{ title }}</c-text>
      <c-text class="text-muted" inline variant="mono-sm">
        <span class="mx-1">{{ '⸱' }}</span>
        <span>enum</span>
      </c-text>
    </div>
    <!-- Embedded puts the clear beside the field rather than in the trailing slot, which is drawn
    over the field and would sit on the value it clears. -->
    <div :class="form.embedded ? 'flex min-w-0 items-center gap-0.5' : 'contents'">
      <c-select-menu
        :class="form.embedded ? 'w-auto font-mono' : 'w-full font-mono'"
        :items="items"
        :model-value="selected"
        :search-input="{ placeholder: 'Filter...' }"
        :size="form.embedded ? 'xs' : 'sm'"
        :ui="{
          base: form.embedded
            ? 'font-mono text-[10px] md:text-[10px] px-0 py-0'
            : 'font-mono text-xs',
          // The popup is sized from its anchor, and an embedded trigger is only as wide as its
          // value, which would cut the options it is offering short.
          content: form.embedded ? 'w-auto min-w-fit' : undefined,
        }"
        :variant="form.embedded ? 'none' : undefined"
        @update:model-value="(item: Item | undefined) => (modelValue = resolve(item?.value))"
      >
        <template v-if="!form.embedded" #trailing>
          <c-schema-form-node-clear-button
            v-if="!isRequired && modelValue !== undefined"
            :embedded="form.embedded"
            @click="onClear"
          />
        </template>
      </c-select-menu>
      <c-schema-form-node-clear-button
        v-if="form.embedded && !isRequired && modelValue !== undefined"
        embedded
        @click="onClear"
      />
    </div>
    <c-text v-if="description && !form.embedded" class="mt-1 ml-3 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
