<script lang="ts" setup>
import { SchemaForm } from '@/schema-form'

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
  <div class="q-col-gutter-sm row">
    <div class="col">
      <q-btn
        class="full-width"
        color="primary"
        dense
        :disable="form == null || !form.canSubmit"
        :label="executeLabel"
        :loading="form?.state === 'submitting'"
        no-caps
        unelevated
        @click="submit"
      />
    </div>
    <div v-if="form == null || !form.isEmpty" class="col">
      <q-btn
        class="full-width"
        color="warning"
        dense
        :disable="form == null || form.readonly || form.isInitialValue"
        :label="resetLabel"
        no-caps
        unelevated
        @click="reset"
      />
    </div>
    <div v-if="cancelLabel != null" class="col">
      <q-btn class="full-width" dense flat :label="cancelLabel" no-caps @click="emit('cancel')" />
    </div>
  </div>
</template>
