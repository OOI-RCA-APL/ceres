<script lang="ts" setup>
import { ComponentInfo, ProcedureInfo } from '@/api/models'
import { call } from '@/api/operations'
import CommonText from '@/components/CommonText.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import { useSchemaForm } from '@/schema-form'
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

const form = useSchemaForm({
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
  <div v-if="!form.isEmpty || form.getDescription([]) != null" class="q-mb-sm">
    <q-card bordered class="q-px-sm q-py-xs" flat>
      <schema-form :key="procedure.name" :form="form" />
    </q-card>
  </div>
  <div>
    <schema-form-controls v-if="form" class="q-mb-sm" :form="form" />
  </div>
  <div>
    <div v-if="resultJson === undefined" class="items-center justify-center q-pa-xs row">
      <common-text variant="description">Results will be displayed here.</common-text>
    </div>
    <q-input
      v-else
      dense
      filled
      :input-class="[$style.output, 'monospace']"
      label="Output"
      :model-value="resultJson"
      readonly
      :rows="8"
      type="textarea"
    >
      <template #label>
        <span class="full-width row">
          <span>Output</span>
          <span :class="$style.outputLabelExtra">
            <template v-if="receivedAt">
              <span class="q-mx-xs">⸱</span>
              <span>
                {{ displayDuration(time.now.diff(receivedAt, 'seconds'), { short: true }) }} ago
              </span>
            </template>
            <template v-if="receivedAt && sentAt">
              <span class="q-mx-xs">⸱</span>
              <span>
                {{ displayDuration(receivedAt.diff(sentAt, 'seconds', true), { short: true }) }}
              </span>
            </template>
          </span>
        </span>
      </template>
    </q-input>
  </div>
</template>

<style module>
.output {
  font-size: 11px;
}

.outputLabelExtra {
  opacity: 0.5;
}
</style>
