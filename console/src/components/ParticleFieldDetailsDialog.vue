<script lang="ts" setup>
import { ParticleFieldInfo } from '@/api/components'
import { describeFieldDescription, describeFieldType } from '@/particle-types'
import { Schema } from '@/schema-form'

/** The field whose details show, with the address and type it belongs to. Null closes. */
export type ParticleFieldDetails = {
  address: string
  type: string
  field: ParticleFieldInfo
}

let details = $(defineModel<ParticleFieldDetails | null>({ required: true }))
</script>

<template>
  <q-dialog
    :model-value="details != null"
    @update:model-value="(value: boolean) => !value && (details = null)"
  >
    <q-card v-if="details != null" bordered flat :style="{ minWidth: '320px' }">
      <div class="column q-gutter-y-sm q-pa-md">
        <div class="items-baseline q-gutter-x-sm row">
          <span class="monospace-sm text-weight-medium">{{ details.field.name }}:</span>
          <span class="monospace-sm text-grey-6">
            {{ describeFieldType(details.field.schema as Schema) }}
          </span>
        </div>
        <div class="monospace-sm text-grey-6">
          {{ details.address }}::particles::{{ details.type }}
        </div>
        <div v-if="describeFieldDescription(details.field.schema)">
          {{ describeFieldDescription(details.field.schema) }}
        </div>
        <div v-else class="text-grey-6">No description.</div>
      </div>
    </q-card>
  </q-dialog>
</template>
