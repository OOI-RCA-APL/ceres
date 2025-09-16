<script lang="ts" setup>
import { watchEffect } from 'vue'

import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import {
  SchemaForm,
  SchemaFormOptions,
  SchemaPath,
  isSchemaForm,
  useSchemaForm,
} from '@/schema-form'

const { form: formInput, formRef } = defineProps<{
  form: SchemaForm | SchemaFormOptions
  formRef?: (form: SchemaForm) => unknown
}>()

const path: SchemaPath = []
const form = isSchemaForm(formInput) ? formInput : useSchemaForm({ ...formInput })

watchEffect(() => {
  if (formRef) {
    formRef(form)
  }
})

function update(value: unknown) {
  form.assign(value)
}
</script>

<template>
  <q-form @submit.prevent>
    <q-banner v-if="form.schemaErrorMessage" class="bg-warning text-dark" dense>
      Failed to generate form due to an invalid JSON schema.
      <div class="q-mt-sm">
        {{ form.schemaErrorMessage }}
      </div>
    </q-banner>
    <template v-else>
      <schema-form-node :form :model-value="form.value" :path @update:model-value="update" />
      <q-markup-table v-if="!form.isValid" bordered class="q-mt-sm" dense flat separator="cell">
        <thead>
          <q-tr>
            <q-th class="text-left">Location</q-th>
            <q-th class="text-left">Error</q-th>
          </q-tr>
        </thead>
        <tbody>
          <q-tr v-for="(error, i) in form.validationErrors" :key="i" class="bg-negative text-white">
            <q-td class="monospace-sm">{{ form.getPathString(error.instancePath) }}</q-td>
            <q-td class="monospace-sm">{{ form.humanizeErrorMessage(error.message ?? '') }}</q-td>
          </q-tr>
        </tbody>
      </q-markup-table>
    </template>
  </q-form>
</template>
