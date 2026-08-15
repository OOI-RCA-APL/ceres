<script lang="ts" setup>
import type { SchemaForm, SchemaPath } from '@/schema-form'

const { form } = defineProps<{
  form: SchemaForm
}>()

const path: SchemaPath = []
</script>

<template>
  <form @submit.prevent>
    <c-alert
      v-if="form.schemaErrorMessage"
      color="warning"
      :description="form.schemaErrorMessage"
      title="Failed to generate form due to an invalid JSON schema."
      variant="subtle"
    />
    <template v-else>
      <c-schema-form-node v-model="form.value" :form :path />
      <div v-if="!form.isValid" class="border-default mt-2 overflow-x-auto rounded-md border">
        <table class="w-full border-collapse text-left">
          <thead>
            <tr>
              <th class="border-default border-b px-2 py-1">
                <c-text variant="th">Location</c-text>
              </th>
              <th class="border-default border-b px-2 py-1"><c-text variant="th">Error</c-text></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(error, index) in form.validationErrors" :key="index" class="text-error">
              <td class="border-default border-b px-2 py-1">
                <c-text variant="mono-sm">{{ form.getPathString(error.instancePath) }}</c-text>
              </td>
              <td class="border-default border-b px-2 py-1">
                <c-text variant="mono-sm">{{
                  form.humanizeErrorMessage(error.message ?? '')
                }}</c-text>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </form>
</template>
