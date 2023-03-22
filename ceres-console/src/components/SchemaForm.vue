<template>
  <q-form @submit.prevent>
    <q-banner v-if="form.schemaError" class="bg-warning text-dark" dense rounded>
      Failed to generate form due to an invalid JSON schema.
    </q-banner>
    <template v-else>
      <schema-form-node
        :model-value="form.value"
        :path="path"
        @update:model-value="(modelValue) => (form.value = modelValue)"
      />
      <q-banner v-if="form.validationErrors" class="bg-negative q-mt-sm text-white" dense rounded>
        <div v-for="(error, i) in form.validationErrors" :key="i">
          {{ error.instancePath?.trim() ? error.instancePath + ': ' : '' }}
          {{ error.message }}
        </div>
      </q-banner>
    </template>
  </q-form>
</template>

<script lang="ts" setup>
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import { provideSchemaForm, Schema, SchemaPath } from '@/json-schema'
import { unset } from '@/symbols'
import { computed, watch, watchEffect } from 'vue'

const { modelValue = unset, schema } = defineProps<{
  modelValue?: unknown
  schema: Schema
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = provideSchemaForm({
  initial: modelValue,
  schema: computed(() => schema),
})

watch(
  () => modelValue,
  () => {
    if (modelValue !== unset) {
      form.value = modelValue
    }
  }
)

watchEffect(() => {
  emit('update:modelValue', form.value)
})

const path: SchemaPath = []
</script>
