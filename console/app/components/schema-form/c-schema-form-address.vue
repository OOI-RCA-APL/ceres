<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'address' }
  path: SchemaPath
}>()

const engine = useEngine()

const title = $computed(() => form.getLabel(path))
const isRequired = $computed(() => form.getRequired(path))
const description = $computed(() => form.getDescription(path))

// Every component the engine carries, which is what an address can name. Offered as a list
// rather than typed out, an address being long and exact.
const items = $computed(() =>
  engine.components.all.map((component) => component.address.toString()),
)

const selected = $computed(() => (typeof modelValue === 'string' ? modelValue : undefined))

function onClear() {
  modelValue = undefined
}
</script>

<template>
  <div :class="form.embedded && 'contents'">
    <div v-if="!form.embedded" class="mb-1 flex items-baseline gap-1">
      <c-text element="span" variant="mono-sm">{{ title }}</c-text>
      <c-text class="text-muted" element="span" variant="mono-sm">
        <span class="mx-1">{{ '⸱' }}</span>
        <span>address</span>
      </c-text>
    </div>
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
            ? 'font-mono text-[9px] md:text-[9px] px-0 py-0'
            : 'font-mono text-xs',
          content: form.embedded ? 'w-auto min-w-fit' : undefined,
        }"
        :variant="form.embedded ? 'none' : undefined"
        @create="(value: string) => (modelValue = value)"
        @update:model-value="(value: string | undefined) => (modelValue = value)"
      >
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
