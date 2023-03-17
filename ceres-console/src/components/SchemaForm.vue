<template>
  <q-form @submit.prevent>
    <q-banner v-if="form.schemaError" class="bg-warning text-dark" dense inline-actions>
      Failed to generate form due to an invalid JSON schema.
    </q-banner>
    <template v-else>
      <schema-form-node
        :model-value="modelValue"
        :schema="schema"
        @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
      />
      <q-banner v-if="form.validationErrors" class="bg-negative" dense>
        {{ form.validationErrorsText }}
      </q-banner>
    </template>
  </q-form>
</template>

<script lang="ts" setup>
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import { provideSchemaForm, Schema } from '@/json-schema'
import { computed } from 'vue'

const { modelValue, schema } = defineProps<{
  modelValue: unknown
  schema: Schema
}>()

defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = provideSchemaForm({
  value: computed(() => modelValue),
  schema: computed(() => schema),
})
</script>
