<script lang="ts" setup>
import SchemaFormComposite from '@/components/schema-form/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'array' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
  click: []
}>()

const array = $computed(() => {
  if (modelValue == null) {
    return modelValue
  }

  if (!Array.isArray(modelValue)) {
    return undefined
  }

  return modelValue as unknown[]
})

if (array !== modelValue) {
  emit('update:modelValue', array)
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
  emit('update:modelValue', withAssigned(index, subvalue))
}

function onAddButtonClicked() {
  const subschema = form.getSchema([...path, array?.length ?? 0])
  if (subschema == null) {
    return
  }

  const initial = form.getInitialValue(subschema)
  emit('update:modelValue', [...(array ?? []), initial])
}
</script>

<template>
  <schema-form-composite
    :form
    :model-value="array"
    :path
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  >
    <div
      v-if="array != null"
      :class="
        form.inline && $q.screen.gt.sm
          ? 'row items-center q-col-gutter-sm q-pa-sm'
          : 'column q-col-gutter-xs q-pa-sm'
      "
    >
      <div v-for="[index, subvalue] in array.entries()" :key="index">
        <schema-form-node
          :form
          :model-value="subvalue"
          no-clear-on-empty
          :path="[...path, index]"
          @update:model-value="(subvalue) => onUpdate(index, subvalue)"
        />
      </div>
      <div class="text-center">
        <schema-form-node-add-button @click="onAddButtonClicked" />
      </div>
    </div>
  </schema-form-composite>
</template>

<style module>
.addButton {
  overflow: hidden;
}

.addButton:hover {
  opacity: 1;
}
</style>
