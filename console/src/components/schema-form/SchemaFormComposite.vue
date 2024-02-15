<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { usePreferences } from '@/preferences'
import { SchemaForm, SchemaPath } from '@/schema-form'
import { isLight } from '@/utilities'

const { modelValue, path, form } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const preferences = usePreferences()

const title = $computed(() => (path.length === 0 ? undefined : form.getLabel(path)))

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

const definedColor = $computed(() => (isRequired ? 'transparent' : 'primary'))
const undefinedColor = $computed(() => (preferences.isDarkModeEnabled ? 'grey-9' : 'grey-5'))

const color = $computed(() => (isDefined ? definedColor : undefinedColor))
const textColor = $computed(() => (isLight(color) ? 'black' : 'white'))
const description = $computed(() => form.getDescription(path))

function toggle() {
  if (isDefined) {
    if (!isRequired) {
      emit('update:modelValue', undefined)
    }
  } else {
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
          isDefined && $style.defined,
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
            <div>
              <q-chip
                v-if="title"
                :class="[$style.title, 'monospace-sm', 'q-mr-sm']"
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
            <div>
              <common-text v-if="description" :class="$style.description" variant="description">
                {{ description }}
              </common-text>
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
}

.titleContainerTitled {
  margin-top: 8px;
  margin-left: 12px;
}

.title {
  padding: 0px 8px;
  outline: 1px solid grey;
  margin-left: 0;
}

.description {
  margin-top: 4px;
}

:not(.defined) .title:focus {
  outline: 1px solid $primary;
}

.defined .title:focus {
  outline: 1px solid white;
}
</style>
