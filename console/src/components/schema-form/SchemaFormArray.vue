<script lang="ts" setup>
import SchemaFormComposite from '@/components/schema-form/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import icons from '@/icons'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'array' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
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

  emit('update:modelValue', [...(array ?? []), form.getInitialValue(subschema)])
}
</script>

<template>
  <schema-form-composite
    :form="form"
    :model-value="array"
    :path="path"
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
          :form="form"
          :model-value="subvalue"
          :path="[...path, index]"
          @update:model-value="(subvalue) => onUpdate(index, subvalue)"
        />
      </div>
      <div class="text-center">
        <q-btn
          :class="$style.addButton"
          clickable
          dense
          :icon="icons.add"
          :ripple="false"
          @click="onAddButtonClicked"
        />
      </div>
    </div>
  </schema-form-composite>
</template>

<style module>
.addButton {
  opacity: 0.75;
  scale: 0.65;
  overflow: hidden;
}

.addButton:hover {
  opacity: 1;
}
</style>
