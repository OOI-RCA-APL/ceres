<script lang="ts" setup>
import { SchemaForm, SchemaPath } from '@/schema-form'
import { useQuasar } from 'quasar'

const { modelValue, path, form } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const quasar = useQuasar()

const title = $computed(() => (path.length === 0 ? undefined : form.getLabel(path)))

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

const definedColor = $computed(() => (isRequired ? 'transparent' : 'primary'))
const undefinedColor = $computed(() => (quasar.dark.isActive ? 'grey-9' : 'grey-5'))

const textColor = $computed(() => (quasar.dark.isActive || isDefined ? 'white' : undefined))
const color = $computed(() => (isDefined ? definedColor : undefinedColor))

function toggle() {
  if (isDefined) {
    if (!isRequired) {
      emit('update:modelValue', undefined)
    }
  } else {
    const schema = form.getSchema(path)
    if (schema) {
      emit('update:modelValue', form.getDefault(schema))
    }
  }
}
</script>

<template>
  <q-card :bordered="path.length > 0 || !isRequired" flat>
    <div
      :class="[
        form.inline && $q.screen.gt.sm ? 'row q-pr-xs' : 'column',
        isDefined && $style.defined,
      ]"
    >
      <template v-if="title">
        <div :class="[$style.titleContainer, 'q-py-xs', 'row']">
          <q-chip
            :class="[$style.title, 'monospace-md']"
            :clickable="!isRequired"
            :color="color"
            dense
            :ripple="!isRequired"
            :text-color="textColor"
            @click="toggle"
          >
            {{ title }}
          </q-chip>
        </div>
        <q-separator v-if="modelValue != null" />
      </template>
      <slot />
    </div>
  </q-card>
</template>

<style lang="scss" module>
.titleContainer {
  min-height: 40px;
  opacity: 0.75;
}

.title {
  margin-top: 6px;
  margin-left: 10px;
}

:not(.defined) .title:focus {
  outline: 1px solid $primary;
}

.defined .title:focus {
  outline: 1px solid white;
}
</style>
