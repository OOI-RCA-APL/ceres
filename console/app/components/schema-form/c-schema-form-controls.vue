<script lang="ts" setup>
import type { SchemaForm } from '@/schema-form'

const {
  form,
  executeLabel = 'Execute',
  resetLabel = 'Reset',
  cancelLabel,
  unavailableReason,
} = defineProps<{
  form?: SchemaForm | null

  executeLabel?: string
  resetLabel?: string

  /** A label for a cancel button, offered only when set, for a form standing somewhere that can
  be backed out of. */
  cancelLabel?: string

  /** Why the form cannot be submitted at all, shown on the disabled execute button. */
  unavailableReason?: string
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
    <!-- The tooltip renders no element of its own, so the wrapper carries the button's share. -->
    <div class="flex-1">
      <c-tooltip :disabled="unavailableReason == null" :text="unavailableReason ?? ''">
        <c-button
          block
          color="primary"
          :disabled="form == null || !form.canSubmit || unavailableReason != null"
          :label="executeLabel"
          :loading="form?.state === 'submitting'"
          size="sm"
          @click="submit"
        />
      </c-tooltip>
    </div>
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
