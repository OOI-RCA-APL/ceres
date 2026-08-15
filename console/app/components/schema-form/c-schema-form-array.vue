<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { cloneDeep } from 'lodash-es'

import icons from '@/icons'
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'array' }
  path: SchemaPath
}>()

const array = $computed(() => {
  if (modelValue == null) {
    return undefined
  }

  if (!Array.isArray(modelValue)) {
    return undefined
  }

  return modelValue as unknown[]
})

if (array !== modelValue) {
  modelValue = array
}

function withAssigned(index: number, subvalue: unknown) {
  if (array == null) {
    return array
  }

  const before = array.slice(0, index)
  const middle = subvalue === undefined ? [] : [subvalue]
  const after = array.slice(index + 1)

  return [...before, ...middle, ...after]
}

function onUpdate(index: number, subvalue: unknown) {
  modelValue = withAssigned(index, subvalue)
}

function onAddButtonClicked() {
  const subschema = form.getSchema([...path, array?.length ?? 0])
  if (subschema == null) {
    return
  }

  const initial = form.getInitialValue(subschema)
  modelValue = [...(array ?? []), initial]
}

function duplicate(index: number) {
  if (array == null || index < 0 || index >= array.length) {
    return
  }

  const before = array.slice(0, index + 1)
  const after = array.slice(index + 1)

  modelValue = [...before, cloneDeep(array[index]), ...after]
}

function remove(index: number) {
  modelValue = withAssigned(index, undefined)
}

function itemMenu(index: number): DropdownMenuItem[] {
  return [
    { label: 'Duplicate', icon: icons.duplicate, onSelect: () => duplicate(index) },
    { label: 'Remove', icon: icons.cancel, onSelect: () => remove(index) },
  ]
}
</script>

<template>
  <c-schema-form-composite
    :form
    :model-value="array"
    :path
    @update:model-value="(value) => (modelValue = value)"
  >
    <div v-if="array != null" class="flex flex-col gap-1 p-2">
      <div v-for="[index, subvalue] in array.entries()" :key="index">
        <div class="relative flex items-center">
          <div class="grow">
            <c-schema-form-node
              :form
              :model-value="subvalue"
              no-clear-on-empty
              :path="[...path, index]"
              @update:model-value="(subvalue) => onUpdate(index, subvalue)"
            />
          </div>
          <c-dropdown-menu :items="itemMenu(index)" size="sm">
            <c-button
              class="absolute top-2 right-0 opacity-40 hover:opacity-100"
              color="neutral"
              :icon="icons.moreVertical"
              size="xs"
              square
              variant="ghost"
            />
          </c-dropdown-menu>
        </div>
      </div>
      <div class="text-center">
        <c-schema-form-node-add-button @click="onAddButtonClicked" />
      </div>
    </div>
  </c-schema-form-composite>
</template>
