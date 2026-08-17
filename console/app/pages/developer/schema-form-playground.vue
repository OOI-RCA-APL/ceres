<script lang="ts" setup>
import { usePersisted } from '@/persistence'
import { type Schema, useSchemaForm } from '@/schema-form'

function createDefaultSchema() {
  return {
    type: 'object',
    properties: {
      name: {
        type: 'string',
        title: 'Name',
      },
      age: {
        type: 'number',
        title: 'Age',
      },
    },
  }
}

const persisted = usePersisted({
  schema: ({ object, string }) =>
    object({
      schemaJson: string().default(() => JSON.stringify(createDefaultSchema(), null, 2)),
    }),
  methods: [{ type: 'local-storage', key: ['state', 'schema-form-playground', 'schema'] }],
})

// Undefined while the text is mid-edit and not yet valid JSON, which the form takes as the
// permissive schema.
const schema = $computed<Schema | undefined>(() => {
  try {
    return JSON.parse(persisted.schemaJson)
  } catch {
    return undefined
  }
})

const form = useSchemaForm({
  schema: () => schema,
  persist: ['state', 'schema-form-playground', 'form'],
})

const panelClass = 'border-default flex-1 rounded-lg border'
const textareaUi = { base: 'font-mono text-xs' }
</script>

<template>
  <div>
    <div>
      <c-text class="block px-4 py-2" element="h1" variant="title2">
        Schema Form Playground
      </c-text>
      <c-separator />
    </div>
    <div class="flex flex-col gap-3 p-3 lg:flex-row lg:items-start">
      <div :class="panelClass">
        <c-text class="block px-3 py-2" element="h2" variant="title3">Schema</c-text>
        <c-separator />
        <c-textarea
          v-model="persisted.schemaJson"
          autoresize
          class="w-full p-3"
          :spellcheck="false"
          :ui="textareaUi"
        />
      </div>
      <div :class="panelClass">
        <c-text class="block px-3 py-2" element="h2" variant="title3">Form</c-text>
        <c-separator />
        <div class="p-3">
          <c-schema-form :form />
        </div>
      </div>
      <div :class="panelClass">
        <c-text class="block px-3 py-2" element="h2" variant="title3">Form Data</c-text>
        <c-separator />
        <c-textarea
          autoresize
          class="w-full p-3"
          :model-value="JSON.stringify(form.value, null, 2)"
          readonly
          :ui="textareaUi"
        />
      </div>
    </div>
  </div>
</template>
