<script lang="ts" setup>
import type { Address } from '@/api/address'
import type { ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { useSchemaForm } from '@/schema-form'
import { utc } from '@/time'
import type { Datetime } from '@/time'
import type { Plain } from '@/utilities'

let argumentsModel: unknown = $(defineModel<unknown>('arguments', { required: false }))

const { address, procedure } = defineProps<{
  address: Address
  procedure: ProcedureInfo
}>()

// With no bound arguments the form keeps its own, remembered per procedure so returning to one
// finds what was last entered.
const hasArgumentsModel = $computed(() => argumentsModel !== undefined)

const engine = useEngine()

let result = $ref<unknown>(undefined)
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
    persist: () => ['state', 'procedure', 'schema-form', address, 'procedures', procedure.name],
  }
})

const form = useSchemaForm({
  ...options,
  schema: () => procedure.arguments.json_schema,
  // Only fields deserve a heading. A procedure taking nothing still shows its description, and an
  // "Arguments" heading over no arguments would only promise fields that never come.
  title: () => (form.isEmpty ? undefined : 'Arguments'),
  async onSubmit(args) {
    sentAt = utc()
    receivedAt = null
    result = await engine.components.call(address, procedure.name, args as Record<string, unknown>)
    receivedAt = utc()
  },
})

if (!form.isValid) {
  form.reset()
}
</script>

<template>
  <div>
    <div
      v-if="!form.isEmpty || form.getDescription([]) != null"
      class="border-default mb-2 rounded-md border p-2"
    >
      <c-schema-form :key="`${address}${procedure.name}`" :form />
    </div>
    <c-schema-form-controls class="mb-2" :form />
    <div v-if="resultJson === undefined" class="flex items-center justify-center p-1">
      <c-text variant="description">Results will be displayed here.</c-text>
    </div>
    <c-procedure-output v-else :received-at :sent-at :value="result" />
  </div>
</template>
