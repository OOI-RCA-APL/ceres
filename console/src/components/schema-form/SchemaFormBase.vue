<script lang="ts" setup>
import { computed, watchEffect } from 'vue'

import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import { SchemaObject, SchemaPath, useSchemaForm } from '@/schema-form'

const { schema } = defineProps<{
  schema: SchemaObject
}>()

const model = defineModel<unknown>()

const path: SchemaPath = []
const form = useSchemaForm({ schema: computed(() => schema), editing: true })

watchEffect(() => {
  form.assign(model.value)
})

watchEffect(() => {
  model.value = form.value
})

function update(value: unknown) {
  form.assign(value)
}
</script>

<template>
  <schema-form-node :form :model-value="form.value" :path @update:model-value="update" />
</template>
