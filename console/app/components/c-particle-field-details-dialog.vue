<script lang="ts" setup>
import type { ParticleFieldInfo } from '@/api/components'
import { describeFieldDescription, describeFieldType } from '@/particle-types'
import type { Schema } from '@/schema-form'

/** The field whose details show, with the address and type it belongs to. Null closes. */
export type ParticleFieldDetails = {
  address: string
  type: string
  field: ParticleFieldInfo
}

let details = $(defineModel<ParticleFieldDetails | null>({ required: true }))
</script>

<template>
  <c-modal :open="details != null" @update:open="(value: boolean) => !value && (details = null)">
    <template #content>
      <div v-if="details != null" class="flex min-w-80 flex-col gap-2 p-4">
        <div class="flex items-baseline gap-2">
          <c-text class="font-medium" inline variant="mono-sm"> {{ details.field.name }}: </c-text>
          <c-text class="text-muted" inline variant="mono-sm">
            {{ describeFieldType(details.field.schema as Schema) }}
          </c-text>
        </div>
        <c-text class="text-muted" variant="mono-sm">
          {{ details.address }}::particles::{{ details.type }}
        </c-text>
        <c-text v-if="describeFieldDescription(details.field.schema)" variant="description">
          {{ describeFieldDescription(details.field.schema) }}
        </c-text>
        <c-text v-else variant="description">No description.</c-text>
      </div>
    </template>
  </c-modal>
</template>
