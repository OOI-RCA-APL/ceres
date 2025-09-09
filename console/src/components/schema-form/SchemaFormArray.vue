<script lang="ts" setup>
import { cloneDeep } from 'lodash-es'

import SchemaFormComposite from '@/components/schema-form/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import icons from '@/icons'
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

function duplicate(index: number) {
  if (array == null || index < 0 || index >= array.length) {
    return
  }

  const before = array.slice(0, index + 1)
  const after = array.slice(index + 1)

  emit('update:modelValue', [...before, cloneDeep(array[index]), ...after])
}

function remove(index: number) {
  emit('update:modelValue', withAssigned(index, undefined))
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
        <div class="items-center relative-position row">
          <div class="col-grow">
            <schema-form-node
              :form
              :model-value="subvalue"
              no-clear-on-empty
              :path="[...path, index]"
              @update:model-value="(subvalue) => onUpdate(index, subvalue)"
            />
          </div>
          <q-btn
            :class="[$style.moreButton, 'faded-hover']"
            dense
            flat
            :icon="icons.moreVertical"
            size="6px"
          >
            <q-menu anchor="top right" :offset="[8, 8]" self="top left">
              <q-card bordered flat>
                <q-list dense>
                  <q-item v-close-popup clickable @click="duplicate(index)">
                    <q-item-section>Duplicate</q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable @click="remove(index)">
                    <q-item-section>Remove</q-item-section>
                  </q-item>
                </q-list>
              </q-card>
            </q-menu>
          </q-btn>
        </div>
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

.moreButton {
  position: absolute;
  right: 4px;
  top: 13px;
  width: 8px;
  padding-left: 0px;
  padding-right: 0px;
}
</style>
