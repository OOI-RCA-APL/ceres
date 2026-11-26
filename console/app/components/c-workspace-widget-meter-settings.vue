<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import type { ParticleFieldRef } from '@/particle-series'
import { fieldUnit } from '@/particle-types'
import { TextWeightModel, useWorkspace } from '@/workspace'
import type { MeterWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MeterWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedParticleAddress = $computed(
  () => workspace.resolveAddress(widget.particleAddress)?.toString() ?? null,
)

// Offered as the unit input's placeholder so a blank setting says what the meter will show.
const declaredUnit = $computed(() => {
  const types =
    resolvedParticleAddress == null
      ? []
      : (engine.components.get(resolvedParticleAddress)?.particles ?? [])
  return fieldUnit(types, widget.particleType, widget.particleField)
})

const thresholds = [
  { key: 'warningBelow', title: 'Warning Below' },
  { key: 'warningAbove', title: 'Warning Above' },
  { key: 'errorBelow', title: 'Error Below' },
  { key: 'errorAbove', title: 'Error Above' },
] as const

// The widget's own fields are the selection, so the tree highlights what is stored and a pick
// writes straight back, single-select since a meter shows one field.
const selected = $computed<ParticleFieldRef[]>({
  get: () => {
    if (
      resolvedParticleAddress == null ||
      widget.particleType == null ||
      widget.particleField == null
    ) {
      return []
    }

    return [
      {
        address: resolvedParticleAddress,
        type: widget.particleType,
        connection: widget.particleConnection ?? null,
        field: widget.particleField,
      },
    ]
  },
  // The picker's entry names the connection, so a pick sets all four at once.
  set: (refs) => {
    const ref = refs[0]
    if (ref != null) {
      useSource(ref.address, ref.type, ref.field, ref.connection)
    }
  },
})

function useSource(address: string, type: string, field: string, connection: string | null) {
  widget.particleAddress = new AddressSelector(address)
  widget.particleType = type
  widget.particleField = field
  widget.particleConnection = connection
}
</script>

<template>
  <c-workspace-widget-settings :widget>
    <!-- A fixed height, since a meter with no field reads out the whole record and the payload
    resizes with every one that arrives, moving the fields below it out from under the pointer. -->
    <div class="border-default mb-4 h-24 overflow-hidden rounded-md border p-2">
      <c-workspace-widget-meter :widget="widget" />
    </div>
    <div>
      <c-text class="mb-2" variant="title2">Data</c-text>
      <c-particle-data-picker
        v-model:selected="selected"
        class="mb-2"
        collapse-unselected
        :focus-search="widget.particleField == null"
        selection-mode="highlight"
        single
      />
      <c-particle-manual-entry
        choose-label="Use"
        class="mb-4"
        @choose="(entry) => useSource(entry.address, entry.type, entry.field, entry.connection)"
      />
      <c-text class="mb-2" variant="title2">Display</c-text>
      <div class="mb-4 grid grid-cols-2 gap-2">
        <c-schema-form-value
          v-model="widget.unit"
          :schema="{
            type: 'string',
            title: 'Unit',
            optional: true,
            default: declaredUnit,
          }"
        />
        <c-schema-form-value
          v-model="widget.decimals"
          :schema="{
            type: 'integer',
            title: 'Decimals',
            minimum: 0,
            maximum: 10,
            default: 2,
          }"
        />
        <c-schema-form-value
          v-model="widget.prefix"
          :schema="{
            type: 'string',
            title: 'Prefix',
            optional: true,
          }"
        />
        <c-schema-form-value
          v-model="widget.suffix"
          :schema="{
            type: 'string',
            title: 'Suffix',
            optional: true,
          }"
        />
        <c-schema-form-value
          v-model="widget.fontSize"
          :schema="{
            type: 'integer',
            title: 'Font Size (px)',
            description: 'Blank fits the text to the meter.',
            optional: true,
            minimum: 1,
            maximum: 60,
          }"
        />
        <c-schema-form-value
          v-model="widget.fontWeight"
          :schema="{
            type: 'string',
            title: 'Font Weight',
            enum: TextWeightModel.options,
          }"
        />
      </div>
      <c-text class="mb-2" variant="title2">Thresholds</c-text>
      <div class="mb-4 grid grid-cols-2 gap-2">
        <c-schema-form-value
          v-for="threshold in thresholds"
          :key="threshold.key"
          v-model="widget[threshold.key]"
          :schema="{ type: 'number', title: threshold.title, optional: true }"
        />
        <c-schema-form-value
          v-model="widget.staleAfter"
          :schema="{
            type: 'string',
            format: 'duration',
            title: 'Stale After',
            description: 'Dims the value once the newest record is older.',
            optional: true,
          }"
        />
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
