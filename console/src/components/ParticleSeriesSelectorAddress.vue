<script lang="ts" setup>
import { Address } from '@/api/address'
import { describeFieldDescription, describeFieldType, useParticleTypes } from '@/particle-types'
import { Schema } from '@/schema-form'
import { ChartWidgetParticle } from '@/workspace'

const {
  address,
  particles,
  defaultOpened = false,
} = defineProps<{
  address: Address
  /** The chart model's particle entries, read to mark which of this address's fields are on. */
  particles: ChartWidgetParticle[]
  defaultOpened?: boolean
}>()

const emit = defineEmits<{
  /** A field's toggle changed for one of this address's declared particle types. */
  toggle: [type: string, field: string, value: boolean]
}>()

let expanded = $ref(defaultOpened)

// Fetched only once expanded, so an address nobody opens costs no request.
const types = $(useParticleTypes(() => (expanded ? address.toString() : null)).types)

// Reads across every matching entry rather than just the first, so a stored widget carrying
// more than one entry for the same address and type still reports every field it toggled on.
function selectedFields(type: string): string[] {
  return particles
    .filter(
      (particle) =>
        (particle.address?.toString() ?? null) === address.toString() && particle.type === type
    )
    .flatMap((particle) => particle.series.map((series) => series.field))
    .filter((field): field is string => field != null)
}

function isFieldSelected(type: string, field: string): boolean {
  return selectedFields(type).includes(field)
}
</script>

<template>
  <q-expansion-item v-model="expanded" dense dense-toggle :label="address.toString()">
    <q-list dense>
      <q-item v-if="types.length === 0">
        <q-item-section>
          <q-item-label class="text-grey-6">No declared particle types.</q-item-label>
        </q-item-section>
      </q-item>
      <q-expansion-item
        v-for="type in types"
        :key="type.type"
        :caption="type.description ?? undefined"
        dense
        dense-toggle
        :label="type.type"
      >
        <q-list dense>
          <q-item v-for="field in type.fields" :key="field.name" v-ripple tag="label">
            <q-item-section side>
              <q-checkbox
                dense
                :model-value="isFieldSelected(type.type, field.name)"
                @update:model-value="
                  (value) => emit('toggle', type.type, field.name, Boolean(value))
                "
              />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ field.name }}</q-item-label>
              <q-item-label caption>
                <span class="monospace-sm">{{ describeFieldType(field.schema as Schema) }}</span>
                <span v-if="describeFieldDescription(field.schema)">
                  &nbsp;&middot; {{ describeFieldDescription(field.schema) }}
                </span>
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-expansion-item>
    </q-list>
  </q-expansion-item>
</template>
