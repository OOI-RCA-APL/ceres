<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import icons from '@/icons'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { displayTimeDelta, parseTimeDelta } from '@/utilities'

const { modelValue } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'number'; format: 'time-delta' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const resolved = $computed(() => resolve(modelValue))

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  try {
    return parseTimeDelta(value as any).asSeconds()
  } catch {
    return undefined
  }
}

function format(value: unknown) {
  const resolved = resolve(value)
  if (resolved == null) {
    return ''
  }

  return String(resolved)
}

const presets = [
  { label: '1 minute', factory: () => resolve('1m') },
  { label: '5 minutes', factory: () => resolve('5m') },
  { label: '15 minutes', factory: () => resolve('15m') },
  { label: '30 minutes', factory: () => resolve('30m') },
  { label: '1 hour', factory: () => resolve('1h') },
  { label: '12 hours', factory: () => resolve('12h') },
  { label: '1 day', factory: () => resolve('1d') },
  { label: '1 week', factory: () => resolve('7d') },
  { label: '1 month', factory: () => resolve('30d') },
  { label: '1 year', factory: () => resolve('365d') },
] as const
</script>

<template>
  <schema-form-input
    :form="form"
    :format="format"
    input-type="text"
    :model-value="modelValue"
    :path="path"
    :resolve="resolve"
    :schema="schema"
    schema-type="time-delta"
    suffix="second(s)"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  >
    <template v-if="resolved != null" #label-append>
      <span class="q-mx-xs">{{ '⸱' }}</span>
      <span>
        {{ displayTimeDelta(resolved, { decimals: 3 }) }}
      </span>
    </template>
    <template #append>
      <q-btn color="primary" flat :icon="icons.settings" round size="8px">
        <q-menu dense>
          <q-list dense>
            <q-item
              v-for="preset in presets"
              :key="preset.label"
              :active="preset.factory() === resolved"
              clickable
              @click="emit('update:modelValue', preset.factory())"
            >
              <q-item-section>
                <q-item-label>{{ preset.label }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </template>
  </schema-form-input>
</template>
