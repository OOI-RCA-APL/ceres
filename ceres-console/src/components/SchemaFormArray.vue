<template>
  <schema-form-composite :path="path" :value="array">
    <div v-if="array != null" class="column q-col-gutter-sm q-pa-sm">
      <div v-for="[i, element] in array.entries()" :key="i">
        <schema-form-node
          :model-value="element"
          :path="[...path, i]"
          :schema="form.getSchema([...path, i])"
          @update:model-value="
            (element) =>
              $emit('update:modelValue', [
                ...(array ?? []).slice(0, i),
                ...(element == undefined ? [] : [element]),
                ...(array ?? []).slice(i + 1),
              ])
          "
        />
      </div>
      <div class="text-center">
        <q-btn
          class="self-add-button"
          clickable
          dense
          :icon="icons.add"
          :ripple="false"
          round
          @click="onAddButtonClicked"
        />
      </div>
    </div>
  </schema-form-composite>
</template>

<script lang="ts" setup>
import SchemaFormComposite from '@/components/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import icons from '@/icons'
import { SchemaObject, SchemaPath, useSchemaForm } from '@/json-schema'

const { modelValue, path = [] } = defineProps<{
  modelValue: unknown
  schema: SchemaObject & { type: 'array' }
  path?: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()

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

function onAddButtonClicked() {
  console.log(array)
  const subschema = form.getSchema([...path, array?.length ?? 0])
  console.log(JSON.stringify(subschema))
  if (subschema == null) {
    return
  }

  emit('update:modelValue', [...(array ?? []), form.createDefault(subschema)])
}
</script>

<style scoped>
.self-add-button {
  opacity: 0.75;
  scale: 0.65;
  overflow: hidden;
}

.self-add-button:hover {
  opacity: 1;
}
</style>
