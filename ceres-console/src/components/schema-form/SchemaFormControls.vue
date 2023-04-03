<script lang="ts" setup>
import { SchemaForm } from '@/schema-form'

const props = defineProps<{
  form?: SchemaForm | null
  submitLabel?: string
  resetLabel?: string
}>()

const form = $computed(() => props.form)
const submitLabel = $computed(() => props.submitLabel ?? 'Submit')
const resetLabel = $computed(() => props.resetLabel ?? 'Reset')

function submit() {
  form?.submit()
}

function reset() {
  form?.reset()
}
</script>

<template>
  <div class="q-col-gutter-sm q-pt-sm row">
    <div>
      <q-btn
        color="primary"
        dense
        :disable="form == null || !form.canSubmit"
        flat
        :label="submitLabel"
        :loading="form?.state === 'submitting'"
        @click="submit"
      />
    </div>
    <div>
      <q-btn
        color="warning"
        dense
        :disable="form == null || form.readonly"
        flat
        :label="resetLabel"
        @click="reset"
      />
    </div>
  </div>
</template>
