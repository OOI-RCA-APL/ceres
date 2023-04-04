<script lang="ts" setup>
import { SchemaForm, SchemaPath } from '@/schema-form'

const { path, form } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const title = $computed(() => (path.length === 0 ? undefined : form.getLabel(path)))
</script>

<template>
  <q-card bordered flat>
    <template v-if="title">
      <div :class="['items-center q-pr-sm q-py-xs row', $style.titleContainer]">
        <div :class="['monospace', $style.title]">
          {{ title }}
        </div>
      </div>
      <q-separator v-if="modelValue != null" />
    </template>
    <slot />
  </q-card>
</template>

<style module>
.titleContainer {
  min-height: 40px;
  opacity: 0.75;
}

.title {
  font-size: 12px;
  font-weight: 400;
  padding-left: 12px;
  padding-right: 12px;
}
</style>
