<script lang="ts" setup>
import { ComponentInfo, ProcedureInfo } from '@/api/models'
import { call } from '@/api/operations'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import { createSchemaForm } from '@/schema-form'
import { displayDuration, useTime } from '@/time'
import moment, { Moment } from 'moment'
import { computed } from 'vue'

const { component, procedure } = defineProps<{
  component: ComponentInfo
  procedure: ProcedureInfo
}>()

let result = $ref<any>(undefined)
let sentAt = $ref<Moment | null>(null)
let receivedAt = $ref<Moment | null>(null)

const resultJson = $computed(() => {
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return undefined
  }
})

const time = useTime()

const form = createSchemaForm({
  persist: computed(
    () => `state/component-procedure/schema-form/${component.address}/procedures/${procedure.name})`
  ),
  schema: computed(() => procedure.args.json_schema),
  async onSubmit(value) {
    sentAt = moment.utc()
    receivedAt = null
    result = await call(component.address, procedure.name, value)
    receivedAt = moment.utc()
  },
})
</script>

<template>
  <schema-form :key="procedure.name" :form="form" />
  <schema-form-controls v-if="form" :form="form" />
  <q-card bordered class="q-mt-sm" flat title="Result">
    <div
      v-if="resultJson === undefined"
      class="items-center justify-center q-pa-sm row"
      :style="{ opacity: 0.5 }"
    >
      Results will be displayed here.
    </div>
    <q-input
      v-else
      dense
      filled
      input-class="monospace"
      :label="'Output - 1 second ago'"
      :loading="form.submitting"
      :model-value="resultJson"
      readonly
      :rows="4"
      type="textarea"
    >
      <template #label>
        <span class="full-width row">
          <span>Output</span>
          <template v-if="receivedAt">
            <span class="q-mx-xs">⸱</span>
            <span style="opacity: 0.5">
              {{ displayDuration(time.now.diff(receivedAt, 'seconds'), { short: true }) }} ago
            </span>
          </template>
          <span v-if="receivedAt && sentAt">
            <span class="q-mx-xs">⸱</span>
            <span style="opacity: 0.5">
              {{ displayDuration(receivedAt.diff(sentAt, 'seconds', true), { short: true }) }}
            </span>
          </span>
        </span>
      </template>
    </q-input>
  </q-card>
</template>
