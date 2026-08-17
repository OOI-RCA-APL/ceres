<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import icons from '@/icons'
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

let isManualEntryOpen = $ref(false)

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

    widget.particleAddress = new AddressSelector(ref.address)
    widget.particleType = ref.type
    widget.particleField = ref.field
  },
})
</script>

<template>
  <c-workspace-widget-settings :widget>
    <div class="border-default mb-4 rounded-md border p-2">
      <c-workspace-widget-meter :widget="widget" />
    </div>
    <div>
      <c-text class="mb-2" variant="title2">Particles</c-text>
      <c-particle-series-selector
        v-model:selected="selected"
        class="mb-2"
        collapse-unselected
        selection-mode="highlight"
        single
      />
      <!-- Collapsed by default since manual entry is the fallback for undeclared fields. -->
      <div class="border-default mb-4 rounded-md border">
        <button
          class="hover:bg-elevated/50 flex w-full items-center gap-1 px-2 py-1 text-left"
          type="button"
          @click="isManualEntryOpen = !isManualEntryOpen"
        >
          <c-icon
            class="text-muted shrink-0 transition-transform"
            :class="isManualEntryOpen && 'rotate-90'"
            :name="icons.chevronRight"
            size="14"
          />
          <c-text variant="body2">Manual Entry</c-text>
        </button>
        <div v-if="isManualEntryOpen" class="flex flex-col gap-2 p-2">
          <c-workspace-address-select
            :model-value="widget.particleAddress?.toString() ?? null"
            @update:model-value="
              (value) =>
                (widget.particleAddress =
                  value != null && value !== '' ? AddressSelector.parse(value) : null)
            "
          />
          <c-particle-type-select
            :address="resolvedParticleAddress"
            :model-value="widget.particleType ?? null"
            @update:model-value="(value) => (widget.particleType = value)"
          />
          <c-particle-field-select
            :address="resolvedParticleAddress"
            :model-value="widget.particleField ?? null"
            :particle-type="widget.particleType ?? null"
            @update:model-value="(value) => (widget.particleField = value)"
          />
        </div>
      </div>
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
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
