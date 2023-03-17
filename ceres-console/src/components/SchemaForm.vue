<template>
  <q-form @submit.prevent>
    <schema-form-node
      :model-value="modelValue"
      :schema="schema"
      @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
    />
    <q-banner class="bg-negative" dense>
      {{ JSON.stringify(form.validation.errors) }}
    </q-banner>
  </q-form>
</template>

<script lang="ts" setup>
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import { provideSchemaForm } from '@/schema-form'
import { Schema } from 'jsonschema'
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
