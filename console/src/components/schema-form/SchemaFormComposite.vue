<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import SchemaFormNodeClearButton from '@/components/schema-form/SchemaFormNodeClearButton.vue'
import { SchemaForm, SchemaPath } from '@/schema-form'

const { modelValue, path, form } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
}>()

const label = $computed(() => (path.length === 0 ? undefined : form.getLabel(path)))

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))
const isShowingHeader = $computed(() => label != null || description != null || !isRequired)

const description = $computed(() => form.getDescription(path))

function create() {
  if (!isDefined) {
    const schema = form.getSchema(path)
    if (schema) {
      emit('update:modelValue', form.getInitialValue(schema))
    }
  }
}
</script>

<template>
  <div>
    <q-card :bordered="path.length > 0 || !isRequired" flat>
      <div :class="['column', isDefined ? $style.defined : $style.notDefined]">
        <div v-if="isShowingHeader">
          <div
            :class="[
              $style.header,
              label != null && $style.headerWithLabel,
              'column',
              'q-col-gutter-y-xs',
            ]"
          >
            <div class="monospace-sm" :class="$style.title">
              {{ label }}
            </div>
            <div class="col">
              <common-text v-if="description" :class="$style.description" variant="description">
                {{ description }}
              </common-text>
            </div>
            <div :class="[$style.buttons, 'col-shrink justify-end row']">
              <schema-form-node-clear-button
                v-if="!isRequired && modelValue !== undefined"
                @click="emit('update:modelValue', undefined)"
              />
              <schema-form-node-add-button v-else-if="modelValue === undefined" @click="create" />
            </div>
          </div>
          <q-separator v-if="modelValue != null && (label || description)" />
        </div>
        <slot />
      </div>
    </q-card>
  </div>
</template>

<style lang="scss" module>
.header {
  position: relative;
  padding-right: 12px;
  padding-bottom: 6px;
}

.header.headerWithLabel {
  margin-top: 4px;
  margin-left: 12px;
  padding-right: 12px;
}

.description {
  padding-bottom: 2px;
}

.label {
  opacity: 1;
}

.title {
  opacity: 1;
  padding-top: 4px;
}

.notDefined .title {
  opacity: 0.8;
}

.buttons {
  position: absolute;
  top: -2px;
  right: 6px;
}
</style>
