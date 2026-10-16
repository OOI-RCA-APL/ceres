<script lang="ts" setup>
import type { SchemaForm, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { path, form } = defineProps<{
  form: SchemaForm
  path: SchemaPath
}>()

const label = $computed(() => (path.length === 0 ? undefined : form.getLabel(path)))

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))
const isRoot = $computed(() => path.length === 0)

// The form's own heading belongs to the root alone. It heads a card holding the fields, set apart
// from the root description above it.
const title = $computed(() => (isRoot ? form.title : undefined))

const description = $computed(() => form.getDescription(path))

const isShowingHeader = $computed(() => label != null || description != null || !isRequired)

function create() {
  if (!isDefined) {
    const schema = form.getSchema(path)
    if (schema) {
      modelValue = form.getInitialValue(schema)
    }
  }
}
</script>

<template>
  <div>
    <div :class="[(!isRoot || !isRequired) && 'border-default rounded-md border']">
      <div class="flex flex-col" :class="isDefined ? undefined : 'opacity-80'">
        <div v-if="isShowingHeader">
          <div
            class="relative flex flex-col gap-1 pr-3 pb-1.5"
            :class="label != null && 'mt-1 ml-3'"
          >
            <c-text v-if="label != null" class="pt-1" variant="mono-sm">{{ label }}</c-text>
            <c-description
              v-if="description"
              class="pb-0.5 text-[11px] text-muted"
              :text="description"
            />
            <div class="absolute -top-0.5 right-1.5 flex justify-end">
              <c-schema-form-node-clear-button
                v-if="!isRequired && modelValue !== undefined"
                :embedded="form.embedded"
                @click="modelValue = undefined"
              />
              <c-schema-form-node-add-button v-else-if="modelValue === undefined" @click="create" />
            </div>
          </div>
          <c-separator v-if="!isRoot && modelValue != null && (label || description)" />
        </div>
        <div v-if="title != null" class="border-default rounded-md border p-2">
          <c-text class="mb-1 block" variant="th">{{ title }}</c-text>
          <slot />
        </div>
        <slot v-else />
      </div>
    </div>
  </div>
</template>
