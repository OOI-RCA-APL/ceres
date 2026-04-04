<script lang="ts" setup>
import { Address } from '@/api/address'
import { ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import { useInterfaceContext } from '@/interface'
import { useSchemaForm } from '@/schema-form'
import { utc, type Datetime } from '@/time'
import { displayDuration, useTime } from '@/time'
import type { Plain } from '@/utilities'

let argumentsModel: unknown = $(defineModel<unknown>('arguments', { required: false }))

const props = defineProps<{
  address: Address
  procedure: ProcedureInfo
}>()

const hasArgumentsModel = $computed(() => argumentsModel !== undefined)
const address = $computed(() => props.address)
const procedure = $computed(() => props.procedure)
const persist = $computed(() => !hasArgumentsModel)

const context = useInterfaceContext()
const time = useTime()
const engine = useEngine()

let result = $ref<any>(undefined)
let sentAt = $ref<Datetime | null>(null)
let receivedAt = $ref<Datetime | null>(null)

const resultJson = $computed(() => {
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return undefined
  }
})

const options = $computed(() => {
  if (hasArgumentsModel) {
    return {
      value: () => argumentsModel as Plain,
      onUpdate: (value: unknown) => {
        argumentsModel = value
      },
    }
  }

  return {
    persist: () =>
      persist
        ? [context.key, 'state', 'procedure', 'schema-form', address, 'procedures', procedure.name]
        : undefined,
  }
})

const form = useSchemaForm({
  ...(options as any),
  schema: () => procedure.arguments.json_schema,
  async onSubmit(args) {
    sentAt = utc()
    receivedAt = null
    result = await engine.components.call(address, procedure.name, args)
    receivedAt = utc()
  },
})

if (!form.isValid) {
  form.reset()
}
</script>

<template>
  <div v-if="!form.isEmpty || form.getDescription([]) != null" class="q-mb-sm">
    <q-card bordered class="q-px-sm q-py-sm" flat>
      <schema-form :key="`${address}${procedure.name}`" :form />
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
                {{ displayDuration(time.now.diff(receivedAt, 'second'), { short: true }) }} ago
              </span>
            </template>
            <template v-if="receivedAt && sentAt">
              <span class="q-mx-xs">⸱</span>
              <span>
                {{ displayDuration(receivedAt.diff(sentAt) / 1000, { short: true }) }}
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
