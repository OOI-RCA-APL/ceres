<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { Plain } from '@/utilities'
import { isEqual } from 'lodash'

const { form, schema, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { enum: Plain[] }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const title = $computed(() => form.getLabel(path))

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
    // Ignore and just return the string value.
  }

  return String(value)
}

const description = $computed(() => form.getDescription(path))

let filterValue = $ref<string | null>(null)

function computeOptions(): Plain[] {
  if (filterValue == null) {
    return [...schema.enum]
  }

  const prefixed = schema.enum.filter((option) => {
    return format(option).startsWith(filterValue)
  })

  if (prefixed.length > 0) {
    return prefixed
  }

  return schema.enum.filter((option) => {
    return format(option).includes(filterValue)
  })
}

let options = $shallowRef(computeOptions())
</script>

<template>
  <div>
    <q-select
      dense
      filled
      input-class="monospace-md"
      label-slot
      :model-value="resolve(modelValue)"
      :option-label="format"
      :options="options"
      options-dense
      @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
    >
      <template #label>
        <div class="monospace-md no-wrap row">
          <span>{{ title }}</span>
          <span :class="$style.labelExtra">
            <span class="q-mx-xs">{{ '⸱' }}</span>
            <span>enum</span>
          </span>
        </div>
      </template>
    </q-select>
    <common-text v-if="description" class="q-ml-sm q-mt-xs" variant="description">
      {{ description }}
    </common-text>
  </div>
</template>

<style module>
.labelExtra {
  opacity: 0.5;
}
</style>
