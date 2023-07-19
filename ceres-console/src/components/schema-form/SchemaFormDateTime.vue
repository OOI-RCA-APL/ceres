<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import icons from '@/icons'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import moment from 'moment'
import { watchEffect } from 'vue'

const { modelValue } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date-time' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: string | null | undefined): void
}>()

const inputPattern = 'YYYY-MM-DD HH:mm:ss.SSS'
const outputPattern = 'YYYY-MM-DD HH:mm:ss.SSS+00:00'

const resolved = $computed(() => resolve(modelValue))
watchEffect(() => {
  console.log(resolved)
})

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  if (typeof value === 'string') {
    if (value.trim() === '') {
      return undefined
    }
  }

  const parsed = moment.utc(value, inputPattern)
  if (parsed.isValid()) {
    return parsed.format(outputPattern)
  }

  return undefined
}

function format(value: unknown) {
  let resolved = resolve(value)
  if (resolved == null) {
    return ''
  }

  if (/.[0]+$/.test(resolved)) {
    resolved = resolved.slice(0, resolved.lastIndexOf('.')).trim()
  }
  if (/:[0]+$/.test(resolved)) {
    resolved = resolved.slice(0, resolved.lastIndexOf(':')).trim()
  }
  if (resolved.endsWith(' 00:00')) {
    resolved = resolved.slice(0, resolved.lastIndexOf(' ')).trim()
  }

  return resolved
}

const presets = [
  {
    label: 'Now',
    factory: () => resolve(moment.utc()),
  },
  {
    label: 'Today (UTC)',
    factory: () => resolve(moment.utc().set({ hour: 0, minute: 0, second: 0, millisecond: 0 })),
  },
  {
    label: 'Yesterday (UTC)',
    factory: () =>
      resolve(
        moment.utc().subtract(1, 'day').set({ hour: 0, minute: 0, second: 0, millisecond: 0 })
      ),
  },
  {
    label: '-1 Hour',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).subtract(1, 'hour')),
  },
  {
    label: '+1 Hour',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).add(1, 'hour')),
  },
  {
    label: '-1 Day',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).subtract(1, 'day')),
  },
  {
    label: '+1 Day',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).add(1, 'day')),
  },
  {
    label: '-1 Week',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).subtract(7, 'days')),
  },
  {
    label: '+1 Week',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).add(7, 'days')),
  },
  {
    label: '-1 Month',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).subtract(7, 'days')),
  },
  {
    label: '+1 Month',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).add(7, 'days')),
  },
  {
    label: '-1 Year',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).subtract(365, 'days')),
  },
  {
    label: '+1 Year',
    factory: () => resolve(moment.utc(resolved ?? moment.utc()).add(365, 'days')),
  },
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
    schema-type="date-time"
    suffix="UTC"
    @update:model-value="(modelValue: any) => emit('update:modelValue', modelValue)"
  >
    <template #append>
      <q-btn color="primary" flat :icon="icons.settings" round size="8px">
        <q-menu class="no-shadow" dense>
          <q-list bordered class="rounded-borders" dense>
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
