<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import type { ParticleFieldRef } from '@/particle-series'
import { TextWeightModel, useWorkspace } from '@/workspace'
import type { MeterWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MeterWidget
}>()

const workspace = useWorkspace()

const resolvedParticleAddress = $computed(
  () => workspace.resolveAddress(widget.particleAddress)?.toString() ?? null,
)

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
        field: widget.particleField,
      },
    ]
  },
  set: (refs) => {
    const ref = refs[0]
    if (ref == null) {
      return
    }

    // A connection belongs to the source it narrowed, so another source starts on none.
    const sameSource = ref.address === resolvedParticleAddress && ref.type === widget.particleType
    const connection = sameSource ? (widget.particleConnection ?? null) : null
    useSource(ref.address, ref.type, ref.field, connection)
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
        selection-mode="highlight"
        single
      />
      <c-particle-manual-entry
        choose-label="Use"
        class="mb-4"
        @choose="(entry) => useSource(entry.address, entry.type, entry.field, entry.connection)"
      />
      <c-text class="mb-2" variant="title2">Display</c-text>
      <div class="mb-2 grid grid-cols-2 gap-2">
        <c-schema-form-value
          v-model="widget.fontSize"
          :schema="{
            type: 'integer',
            title: 'Font Size (px)',
            optional: true,
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
          v-model="widget.decimals"
          :schema="{
            type: 'integer',
            title: 'Decimals',
            minimum: 0,
            maximum: 10,
            default: 2,
          }"
        />
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
