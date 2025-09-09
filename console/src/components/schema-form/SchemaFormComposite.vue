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

const title = $computed(() => (path.length === 0 ? undefined : form.getLabel(path)))

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

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
      <div
        :class="[
          form.inline && $q.screen.gt.sm ? 'row q-pr-xs' : 'column',
          isDefined ? $style.defined : $style.notDefined,
        ]"
      >
        <template v-if="title || description">
          <div
            :class="[
              $style.titleContainer,
              title != null && $style.titleContainerTitled,
              'row',
              'q-mb-xs',
            ]"
          >
            <div class="monospace-sm q-mr-sm">
              {{ title }}
            </div>
            <div>
              <common-text v-if="description" :class="$style.description" variant="description">
                {{ description }}
              </common-text>
            </div>
            <q-space />
            <div>
              <q-space />
              <schema-form-node-clear-button
                v-if="!isRequired && modelValue !== undefined"
                @click="emit('update:modelValue', undefined)"
              />
              <schema-form-node-add-button v-else-if="modelValue === undefined" @click="create" />
            </div>
          </div>
          <q-separator v-if="modelValue != null && title" />
        </template>
        <slot />
      </div>
    </q-card>
  </div>
</template>

<style lang="scss" module>
.titleContainer {
  margin-bottom: 8px;
  padding-right: 12px;
}

.titleContainerTitled {
  margin-top: 8px;
  margin-left: 12px;
  padding-right: 12px;
}

.title {
  padding: 0px 4px;
  margin-left: 0;
}

.description {
  margin-top: 1px;
}

.title {
  opacity: 1;
}

.notDefined .title {
  opacity: 0.5;
}

.defined .title:focus {
  outline: 1px solid white;
}
</style>
