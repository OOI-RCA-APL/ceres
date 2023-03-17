<template>
  <q-card bordered flat>
    <template v-if="label">
      <div class="items-center q-px-sm q-py-xs row">
        <div>
          <common-text variant="title2">
            {{ label }}
          </common-text>
        </div>
        <div>
          <q-btn
            v-if="!required || value == null"
            class="self-toggle-button"
            dense
            :icon="value ? icons.remove : icons.add"
            round
            @click="onToggleButtonClicked"
          >
            <q-tooltip :delay="1000">{{ value ? 'Remove' : 'Add' }}</q-tooltip>
          </q-btn>
        </div>
      </div>
      <q-separator v-if="value" />
    </template>
    <div v-if="value" class="column q-col-gutter-sm q-pa-sm">
      <div v-for="[property, subschema] in Object.entries(schema.properties ?? {})" :key="property">
        <schema-form-node
          :model-value="value[property]"
          :path="[...path, property]"
          :schema="subschema"
          @update:model-value="
            (subvalue) => $emit('update:modelValue', { ...value, [property]: subvalue })
          "
        />
      </div>
    </div>
  </q-card>
</template>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import icons from '@/icons'
import { Path, useSchemaForm } from '@/schema-form'
import { Schema } from 'jsonschema'

const {
  modelValue,
  schema,
  path = [],
} = defineProps<{
  modelValue: unknown
  schema: Schema & { type: 'object' }
  path?: Path
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  if (typeof value !== 'object' || Array.isArray(value)) {
    return undefined
  }

  return value as Record<string, unknown>
}

const value = $computed(() => resolve(modelValue))
if (value !== modelValue) {
  emit('update:modelValue', value)
}

function onToggleButtonClicked() {
  if (value) {
    emit('update:modelValue', undefined)
  } else {
    emit('update:modelValue', form.createDefault(schema))
  }
}

const required = $computed(() => form.isRequired(path))
const label = $computed(() => form.getLabel(path))
</script>

<style scoped>
.self-toggle-button {
  opacity: 0.75;
  scale: 0.65;
}

.self-toggle-button:hover {
  opacity: 1;
}
</style>
