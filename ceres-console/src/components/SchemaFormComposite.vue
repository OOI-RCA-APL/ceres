<template>
  <q-card bordered flat>
    <template v-if="title">
      <div class="items-center q-py-xs row">
        <div class="self-title">
          {{ title }}
        </div>
      </div>
      <q-separator v-if="modelValue != null" />
    </template>
    <slot />
  </q-card>
</template>

<script lang="ts" setup>
import { SchemaPath, useSchemaForm } from '@/json-schema'

const { path } = defineProps<{
  modelValue: unknown
  path: SchemaPath
}>()

const form = useSchemaForm()
const title = $computed(() => (path.length === 0 ? undefined : form.getTitle(path)))
</script>

<style scoped>
.self-title {
  font-size: 15px;
  font-weight: 400;
  padding-left: 10px;
}

.body--dark .self-title {
  color: white;
  opacity: 0.75;
}
</style>
