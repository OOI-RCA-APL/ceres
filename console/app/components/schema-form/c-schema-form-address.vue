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
  <div :class="form.compact && 'contents'">
    <div v-if="!form.compact" class="mb-1 flex items-baseline gap-1">
      <c-text element="span" variant="mono-sm">{{ title }}</c-text>
      <c-text class="text-muted" element="span" variant="mono-sm">
        <span class="mx-1">{{ '⸱' }}</span>
        <span>address</span>
      </c-text>
    </div>
    <!-- Compact puts the clear beside the field rather than in the trailing slot, which is drawn
    over the field and would sit on the value it clears. -->
    <div :class="form.compact ? 'flex min-w-0 items-center gap-0.5' : 'contents'">
      <c-select-menu
        :class="form.compact ? 'w-auto font-mono' : 'w-full font-mono'"
        create-item
        :items="items"
        :model-value="selected"
        :search-input="{ placeholder: 'Filter...' }"
        :size="form.compact ? 'xs' : 'sm'"
        :ui="{
          base: form.compact ? 'font-mono text-[9px] px-0 py-0' : 'font-mono text-xs',
          content: form.compact ? 'w-auto min-w-fit' : undefined,
        }"
        :variant="form.compact ? 'none' : undefined"
        @create="(value: string) => (modelValue = value)"
        @update:model-value="(value: string | undefined) => (modelValue = value)"
      >
        <template v-if="!form.compact" #trailing>
          <c-schema-form-node-clear-button
            v-if="!isRequired && modelValue !== undefined"
            :compact="form.compact"
            @click="onClear"
          />
        </template>
      </c-select-menu>
      <c-schema-form-node-clear-button
        v-if="form.compact && !isRequired && modelValue !== undefined"
        compact
        @click="onClear"
      />
    </div>
    <c-text v-if="description && !form.compact" class="mt-1 ml-3 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
