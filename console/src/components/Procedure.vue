<script lang="ts" setup>
import { Address } from '@/api/address'
import { ProcedureInfo } from '@/api/systems'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import { useInterfaceContext } from '@/interface'
import { useSchemaForm } from '@/schema-form'
import { displayDuration, useTime } from '@/time'
import moment, { Moment } from 'moment'
import { computed } from 'vue'

const { address, procedure } = defineProps<{
  address: Address
  procedure: ProcedureInfo
}>()

const context = useInterfaceContext()
const time = useTime()
const engine = useEngine()

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

const form = useSchemaForm({
  persist: computed(() => [
    context.key,
    'state',
    'procedure',
    'schema-form',
    address,
    'procedures',
    procedure.name,
  ]),
  schema: computed(() => procedure.arguments.json_schema),
  async onSubmit(value) {
    sentAt = moment.utc()
    receivedAt = null
    result = await engine.systems.call(address, procedure.name, value)
    receivedAt = moment.utc()
  },
})
</script>

<template>
  <div v-if="!form.isEmpty || form.getDescription([]) != null" class="q-mb-sm">
    <q-card bordered class="q-px-sm q-py-xs" flat>
      <schema-form :key="procedure.name" :form />
    </q-card>
  </div>
  <div>
    <schema-form-controls v-if="form" class="q-mb-sm" :form />
  </div>
  <div>
    <div v-if="resultJson === undefined" class="items-center justify-center q-pa-xs row">
      <common-text variant="description">Results will be displayed here.</common-text>
    </div>
    <q-input
      v-else
      dense
      :input-class="[$style.output, 'monospace']"
      label="Output"
      :model-value="resultJson"
      outlined
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
