<script lang="ts" setup>
import type { SchemaForm } from '@/schema-form'

const {
  form,
  executeLabel = 'Execute',
  resetLabel = 'Reset',
  cancelLabel,
} = defineProps<{
  form?: SchemaForm | null

  executeLabel?: string
  resetLabel?: string

  /** A label for a cancel button, offered only when set, for a form standing somewhere that can
  be backed out of. */
  cancelLabel?: string
}>()

const emit = defineEmits<{
  cancel: []
}>()

function submit() {
  form?.submit()
}

function reset() {
  form?.reset()
}
</script>

<template>
  <div class="flex gap-2">
    <c-button
      block
      class="flex-1"
      color="primary"
      :disabled="form == null || !form.canSubmit"
      :label="executeLabel"
      :loading="form?.state === 'submitting'"
      size="sm"
      @click="submit"
    />
    <c-button
      v-if="form == null || !form.isEmpty"
      block
      class="flex-1"
      color="warning"
      :disabled="form == null || form.readonly || form.isInitialValue"
      :label="resetLabel"
      size="sm"
      @click="reset"
    />
    <c-button
      v-if="cancelLabel != null"
      block
      class="flex-1"
      color="neutral"
      :label="cancelLabel"
      size="sm"
      variant="ghost"
      @click="emit('cancel')"
    />
  </div>
</template>
