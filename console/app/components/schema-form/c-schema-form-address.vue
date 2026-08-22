<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, path, schema } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'address' }
  path: SchemaPath
}>()

const engine = useEngine()

const title = $computed(() => form.getLabel(path))
const isRequired = $computed(() => form.getRequired(path))
const description = $computed(() => form.getDescription(path))

// The addresses to offer, taken from the schema where whoever built it narrowed them. Without
// such a list every component the engine carries is offered, that being what an address can
// name. Offered as a list rather than typed out, an address being long and exact.
const items = $computed(() => {
  const named = schema.examples
  if (Array.isArray(named) && named.length > 0) {
    return named.map(String)
  }

  return engine.components.all.map((component) => component.address.toString())
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
      schema-type="address"
      :show-type="form.showTypes"
    />
    <!-- Embedded puts the clear beside the field rather than in the trailing slot, which is drawn
    over the field and would sit on the value it clears. -->
    <div :class="form.embedded ? 'flex min-w-0 items-center gap-0.5' : 'contents'">
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
        <!-- The value alone, since "Create" reads as making a component rather than as filtering
        on an address the engine is not carrying right now. -->
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
