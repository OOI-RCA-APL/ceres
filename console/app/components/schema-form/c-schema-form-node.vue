<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { nextTick, watchEffect } from 'vue'

import { isType } from '@/schema-form'
import type { SchemaForm, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

function update(value: unknown) {
  modelValue = value
}

const { form, path, noClearOnEmpty } = defineProps<{
  form: SchemaForm
  path: SchemaPath
  noClearOnEmpty?: boolean
}>()

const schema = $computed(() => form.getSchema(path))
const forward = $computed(() => ({
  class: 'grow',
  form,
  modelValue,
  path,
  schema: schema as any,
  noClearOnEmpty,
}))

function is(type: string) {
  if (schema == null) {
    return false
  }

  return isType(schema, type)
}

let root = $ref<HTMLElement | null>(null)

/** Where the indicator is drawn, which is against the field's own control.

A leaf's label and description sit in this box too, and a bar spanning them reads as belonging to
the whole row rather than to the value. Container nodes keep the full height, the control they
would measure being one of their children's.
*/
let indicatorBox = $ref<{ top: number; height: number } | null>(null)

function measure() {
  // Embedded, the bar belongs to the host and spans it, so there is no control to measure against.
  if (form.embedded || root == null || schema == null || is('object') || is('array')) {
    indicatorBox = null
    return
  }

  const control = root.querySelector<HTMLElement>('input, textarea, [role="combobox"], button')
  if (control == null) {
    indicatorBox = null
    return
  }

  // A dialog opening under a scale transition hands back rectangles in the size it is drawn at
  // that moment, so the scale is divided back out and the bar is placed in the field's own
  // units however far through the animation this runs.
  const box = control.getBoundingClientRect()
  const scale = control.offsetHeight > 0 ? box.height / control.offsetHeight : 1
  const offset = box.top - root.getBoundingClientRect().top
  indicatorBox = {
    top: scale > 0 ? offset / scale : offset,
    height: control.offsetHeight,
  }
}

useResizeObserver($$(root), measure)
watchEffect(() => {
  void modelValue
  void schema
  void nextTick(measure)
})

function isFormat(format: string) {
  if (schema == null) {
    return false
  }

  if (typeof schema === 'boolean') {
    return false
  }

  if (schema.format === format) {
    return true
  }

  if (schema.anyOf) {
    return schema.anyOf.some((option) => typeof option === 'object' && option.format === format)
  }

  return false
}
</script>

<template>
  <!-- One root, as an element rather than a `template`, so a class given to a field reaches it.
  A pair of `template` branches is a fragment, and a fragment inherits no attributes at all. -->
  <div v-if="schema == null">
    Unable to resolve schema definition at path: {{ JSON.stringify(path) }}
  </div>
  <!-- Embedded, the node is not the positioning context, so the bar resolves against the host
  and is drawn at its edge rather than partway into it. -->
  <div v-else ref="root" :class="!form.embedded && 'relative'">
    <template v-if="typeof schema === 'boolean'">
      <c-schema-form-any v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="schema.enum != null">
      <c-schema-form-enum v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="is('boolean')">
      <c-schema-form-boolean v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="is('integer')">
      <c-schema-form-integer v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="is('number')">
      <c-schema-form-number v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="is('string')">
      <c-schema-form-date-time
        v-if="isFormat('date-time')"
        v-bind="forward"
        @update:model-value="update"
      />
      <c-schema-form-date
        v-else-if="isFormat('date')"
        v-bind="forward"
        @update:model-value="update"
      />
      <c-schema-form-duration
        v-else-if="isFormat('duration')"
        v-bind="forward"
        @update:model-value="update"
      />
      <c-schema-form-address-selector
        v-else-if="isFormat('address-selector')"
        v-bind="forward"
        @update:model-value="update"
      />
      <c-schema-form-address
        v-else-if="isFormat('address')"
        v-bind="forward"
        @update:model-value="update"
      />
      <c-schema-form-connection
        v-else-if="isFormat('connection')"
        v-bind="forward"
        @update:model-value="update"
      />
      <c-schema-form-string v-else v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="is('array')">
      <c-schema-form-array v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else-if="is('object')">
      <c-schema-form-object v-bind="forward" @update:model-value="update" />
    </template>
    <template v-else>
      <c-schema-form-any v-bind="forward" @update:model-value="update" />
    </template>
    <c-schema-form-node-value-indicator
      class="absolute left-0"
      :class="indicatorBox == null && 'top-0 h-full'"
      :form
      :model-value="modelValue"
      :path
      :style="{
        zIndex: path.length,
        ...(indicatorBox != null
          ? { top: `${indicatorBox.top}px`, height: `${indicatorBox.height}px` }
          : {}),
      }"
    />
  </div>
</template>
