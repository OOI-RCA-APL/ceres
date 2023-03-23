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
import {
  createSchemaForm,
  isSchemaForm,
  SchemaForm,
  SchemaFormOptions,
  SchemaPath,
} from '@/schema-form'

const props = defineProps<{
  form: SchemaForm | SchemaFormOptions
}>()

const path: SchemaPath = []
const form = $computed(() =>
  isSchemaForm(props.form) ? props.form : createSchemaForm({ ...props.form })
)
</script>
