<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, path, schema } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'connection' }
  path: SchemaPath
}>()

const engine = useEngine()

const title = $computed(() => form.getLabel(path))
const isRequired = $computed(() => form.getRequired(path))
const description = $computed(() => form.getDescription(path))

// The names to offer, taken from the schema where whoever built it narrowed them. A filter bar
// names the connections its address filter can reach, and without such a list every connection
// the engine carries is offered. A name is unique only within its own component, so the same one
// stands for every component declaring it.
const items = $computed(() => {
  const named = schema.examples
  if (Array.isArray(named) && named.length > 0) {
    return named.map(String)
  }

  return [
    ...new Set(
      engine.components.all.flatMap((component) =>
        component.connections.map((connection) => connection.name),
      ),
    ),
  ]
})

const selected = $computed(() => (typeof modelValue === 'string' ? modelValue : undefined))

function onClear() {
  modelValue = undefined
}
</script>

<template>
  <div :class="form.embedded && 'contents'">
    <c-schema-form-node-label
      v-if="!form.embedded"
      :align="form.align"
      :label="title"
      schema-type="connection"
      :show-type="form.showTypes"
    />
    <!-- Embedded puts the clear beside the field rather than in the trailing slot, which is drawn
    over the field and would sit on the value it clears. -->
    <div :class="form.embedded ? 'flex min-w-0 items-center gap-0.5' : 'contents'">
      <!-- Created as typed as well as chosen, since a connection the engine is not carrying now
      still named the records that are being looked through. -->
      <c-select-menu
        :class="form.embedded ? 'w-auto font-mono' : 'w-full font-mono'"
        create-item
        :items="items"
        :model-value="selected"
        :search-input="{ placeholder: 'Filter...' }"
        :size="form.embedded ? 'xs' : 'sm'"
        :ui="{
          base: form.embedded
            ? 'font-mono text-[10px] md:text-[10px] px-0 py-0'
            : 'font-mono text-xs',
          content: form.embedded ? 'w-auto min-w-fit' : undefined,
        }"
        :variant="form.embedded ? 'none' : undefined"
        @create="(value: string) => (modelValue = value)"
        @update:model-value="(value: string | undefined) => (modelValue = value)"
      >
        <template #create-item-label="{ item }">
          <span class="font-mono">"{{ item }}"</span>
        </template>
        <template v-if="!form.embedded" #trailing>
          <c-schema-form-node-clear-button
            v-if="!isRequired && modelValue !== undefined"
            :embedded="form.embedded"
            @click="onClear"
          />
        </template>
      </c-select-menu>
      <c-schema-form-node-clear-button
        v-if="form.embedded && !isRequired && modelValue !== undefined"
        embedded
        @click="onClear"
      />
    </div>
    <c-text v-if="description && !form.embedded" class="mt-1 ml-3 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
