<script lang="ts" setup>
import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import {
  createSchemaForm,
  isSchemaForm,
  SchemaForm,
  SchemaFormOptions,
  SchemaPath,
} from '@/schema-form'
import { watchEffect } from 'vue'

const props = defineProps<{
  form: SchemaForm | SchemaFormOptions
  formRef?: (form: SchemaForm) => unknown
}>()

const path: SchemaPath = []
const form = isSchemaForm(props.form) ? props.form : createSchemaForm({ ...props.form })

watchEffect(() => {
  if (props.formRef) {
    props.formRef(form)
  }
})

function update(value: unknown) {
  form.assign(value)
}
</script>

<template>
  <q-form @submit.prevent>
    <q-banner v-if="form.schemaError" class="bg-warning text-dark" dense rounded>
      Failed to generate form due to an invalid JSON schema.
    </q-banner>
    <template v-else>
      <schema-form-node
        :form="form"
        :model-value="form.value"
        :path="path"
        @update:model-value="update"
      />
      <q-markup-table v-if="!form.isValid" bordered class="q-mt-sm" dense flat separator="cell">
        <thead>
          <q-tr>
            <q-td class="text-left">Location</q-td>
            <q-td class="text-left">Problem</q-td>
          </q-tr>
        </thead>
        <tbody>
          <q-tr v-for="(error, i) in form.validationErrors" :key="i" class="bg-negative">
            <q-td class="monospace-sm">{{ error.instancePath }}</q-td>
            <q-td class="monospace-sm">{{ error.message }}</q-td>
          </q-tr>
        </tbody>
      </q-markup-table>
    </template>
  </q-form>
</template>
