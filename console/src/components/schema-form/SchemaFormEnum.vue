<script lang="ts" setup>
import { isEqual } from 'lodash-es'

import CommonText from '@/components/CommonText.vue'
import SchemaFormNodeClearButton from '@/components/schema-form/SchemaFormNodeClearButton.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { Plain } from '@/utilities'

const { form, schema, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { enum: Plain[] }
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
}>()

const title = $computed(() => form.getLabel(path))
const isRequired = $computed(() => form.getRequired(path))

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
      :class="$style.input"
      dense
      filled
      hide-dropdown-icon
      input-class="monospace-md"
      label-slot
      :model-value="resolve(modelValue)"
      :option-label="format"
      :options="options"
      options-dense
      :popup-content-class="$style.popup"
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
      <template #append>
        <schema-form-node-clear-button
          v-if="!isRequired && modelValue !== undefined"
          @click="emit('update:modelValue', undefined)"
        />
      </template>
    </q-select>
    <common-text v-if="description" :class="$style.description" variant="description">
      {{ description }}
    </common-text>
  </div>
</template>

<style lang="scss" module>
@import '@/css/app.scss';

.labelExtra {
  opacity: 0.5;
}

.input :global(.q-field__native) {
  @extend .monospace-md;
}

.popup {
  @extend .monospace-md;
}

.description {
  margin-top: 4px;
  margin-left: 12px;
  padding-bottom: 4px;
}
</style>
