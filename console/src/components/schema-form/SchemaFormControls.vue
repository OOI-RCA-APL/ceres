<script lang="ts" setup>
import { SchemaForm } from '@/schema-form'

const {
  form,
  executeLabel = 'Execute',
  resetLabel = 'Reset',
} = defineProps<{
  form?: SchemaForm | null
  executeLabel?: string
  resetLabel?: string
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
        unelevated
        @click="reset"
      />
    </div>
  </div>
</template>
