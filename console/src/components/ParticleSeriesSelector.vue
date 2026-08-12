<script lang="ts" setup>
import { reactive } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import ParticleFieldSelect from '@/components/ParticleFieldSelect.vue'
import ParticleSeriesSelectorAddress from '@/components/ParticleSeriesSelectorAddress.vue'
import ParticleTypeSelect from '@/components/ParticleTypeSelect.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import icons from '@/icons'
import {
  ParticleFieldRef,
  addParticleSeries,
  fieldRefKey,
  removeParticleSeries,
  toggleParticleField,
} from '@/particle-series'
import {
  ChartWidgetParticle,
  ChartWidgetSeries,
  ChartWidgetSeriesModel,
  SelectMode,
  useWorkspace,
} from '@/workspace'

const {
  address: pinnedAddress,
  showSelected = false,
  selectionMode = 'toggle',
  single = false,
  itemActions = false,
} = defineProps<{
  /** Fixes the tree to this one address rather than a workspace's placement subtree, the
  component page's case. */
  address?: string | null
  /** Whether the "Selected Particle Series" section renders below the tree. Requires a
  workspace context so only a host without a pinned address sets this. */
  showSelected?: boolean
  /** Whether fields toggle into the model or select as highlighted rows for the host to act
  on through `selected`. */
  selectionMode?: 'toggle' | 'highlight'
  /** Caps the highlight selection at one field, for hosts choosing a single value. */
  single?: boolean
  /** Renders a more-actions button on each field row, wired to `itemContext` like a right
  click. */
  itemActions?: boolean
}>()

const emit = defineEmits<{
  /** A right click landed on a field row and the selection now includes it. */
  itemContext: [event: MouseEvent]
}>()

let modelValue = $(defineModel<ChartWidgetParticle[]>({ default: () => [] }))

/** The highlight-mode selection, in the order the rows were chosen. */
let selected = $(defineModel<ParticleFieldRef[]>('selected', { default: () => [] }))

const selectedKeys = $computed(() => new Set(selected.map(fieldRefKey)))

// Declared types by address, kept for range extension across everything the tree has loaded.
const loadedTypes = reactive(new Map<string, ParticleTypeInfo[]>())

// Every loaded field in tree order, which is what a shift range extends across.
const flatOrder = $computed<ParticleFieldRef[]>(() =>
  addressNodes.flatMap((node) => {
    const address = node.toString()
    return (loadedTypes.get(address) ?? []).flatMap((type) =>
      type.fields.map((field) => ({ address, type: type.type, field: field.name }))
    )
  })
)

// The row a shift range extends from, whichever was last chosen on its own.
let anchor = $ref<string | null>(null)

function onSelect(address: string, type: string, field: string, mode: SelectMode) {
  const ref: ParticleFieldRef = { address, type, field }
  const key = fieldRefKey(ref)

  if (single || mode === 'replace') {
    selected = [ref]
    anchor = key
    return
  }

  if (mode === 'toggle') {
    selected = selectedKeys.has(key)
      ? selected.filter((current) => fieldRefKey(current) !== key)
      : [...selected, ref]
    anchor = key
    return
  }

  const from = flatOrder.findIndex((current) => fieldRefKey(current) === anchor)
  const to = flatOrder.findIndex((current) => fieldRefKey(current) === key)
  if (from === -1 || to === -1) {
    selected = [ref]
    anchor = key
    return
  }

  selected = flatOrder.slice(Math.min(from, to), Math.max(from, to) + 1)
}

// A right click acts on the selection, so a row outside it becomes the selection first.
function onContext(address: string, type: string, field: string, event: MouseEvent) {
  const ref: ParticleFieldRef = { address, type, field }
  if (!selectedKeys.has(fieldRefKey(ref))) {
    selected = [ref]
    anchor = fieldRefKey(ref)
  }

  emit('itemContext', event)
}

const engine = useEngine()

// Not called when the address is pinned since the component page hosts this outside any
// workspace's own tree.
const workspace = pinnedAddress == null ? useWorkspace() : null

const addressNodes = $computed<Address[]>(() => {
  if (pinnedAddress != null) {
    try {
      return [Address.parse(pinnedAddress)]
    } catch {
      return []
    }
  }

  const all = engine.components.all.map((component) => component.address)
  const scope = workspace?.scope ?? null
  if (scope == null || scope.isEngine) {
    return all
  }

  const base = scope.toString()
  return all.filter((address) => {
    const value = address.toString()
    return value === base || value.startsWith(`${base}.`)
  })
})

function toggleField(address: string, type: string, field: string, value: boolean) {
  modelValue = toggleParticleField(modelValue, address, type, field, value)
}

type SelectedTypeGroup = { type: string; series: ChartWidgetSeries[] }
type SelectedAddressGroup = { address: string; types: SelectedTypeGroup[] }

// Grouped for display under the same address/type hierarchy the tree uses, merging any stored
// entries that happen to share an address and type rather than assuming one entry per pair.
const selectedGroups = $computed<SelectedAddressGroup[]>(() => {
  const byAddress = new Map<string, Map<string, ChartWidgetSeries[]>>()

  for (const particle of modelValue) {
    const address = particle.address?.toString() ?? '(no address)'
    const type = particle.type ?? '(no type)'
    const byType = byAddress.get(address) ?? new Map<string, ChartWidgetSeries[]>()
    byType.set(type, [...(byType.get(type) ?? []), ...particle.series])
    byAddress.set(address, byType)
  }

  return [...byAddress.entries()].map(([address, byType]) => ({
    address,
    types: [...byType.entries()].map(([type, series]) => ({ type, series })),
  }))
})

function removeSeries(seriesId: string) {
  modelValue = removeParticleSeries(modelValue, seriesId)
}

let manualAddress = $ref<string | null>(null)
let manualType = $ref<string | null>(null)
let manualField = $ref<string | null>(null)
let manualLabel = $ref<string | null>(null)

const manualResolvedAddress = $computed(
  () => workspace?.resolveAddress(manualAddress)?.toString() ?? manualAddress
)

/** Add a manual entry for an undeclared type or field, merging into an existing address and
type entry the way a toggle does. Only the field and label reset. */
function addManualEntry() {
  if (manualAddress == null || manualType == null || manualField == null) {
    return
  }

  const address = manualResolvedAddress
  if (address == null) {
    return
  }

  const series = ChartWidgetSeriesModel.parse({ field: manualField, label: manualLabel })
  modelValue = addParticleSeries(modelValue, address, manualType, series)
  manualField = null
  manualLabel = null
}
</script>

<template>
  <div>
    <q-list bordered class="rounded-borders" dense>
      <q-item v-if="addressNodes.length === 0">
        <q-item-section>
          <q-item-label class="text-grey-6">No components in this scope.</q-item-label>
        </q-item-section>
      </q-item>
      <particle-series-selector-address
        v-for="node in addressNodes"
        :key="node.toString()"
        :address="node"
        :bare="addressNodes.length === 1"
        :item-actions="itemActions"
        :particles="modelValue"
        :selected-keys="selectedKeys"
        :selection-mode="selectionMode"
        @context="(type, field, event) => onContext(node.toString(), type, field, event)"
        @loaded="(types) => loadedTypes.set(node.toString(), types)"
        @select="(type, field, mode) => onSelect(node.toString(), type, field, mode)"
        @toggle="(type, field, value) => toggleField(node.toString(), type, field, value)"
      />
    </q-list>

    <template v-if="showSelected">
      <div class="q-mt-md q-pb-xs">
        <common-text variant="th">Selected Particle Series</common-text>
      </div>
      <q-list bordered class="rounded-borders" dense>
        <q-item v-if="selectedGroups.length === 0">
          <q-item-section>
            <q-item-label class="text-grey-6">No particle series selected.</q-item-label>
          </q-item-section>
        </q-item>
        <template v-for="group in selectedGroups" :key="group.address">
          <template v-for="typeGroup in group.types" :key="`${group.address}|${typeGroup.type}`">
            <!-- The established path notation, one line standing in for the address and type
            levels. -->
            <q-item :class="$style.groupHeader" dense>
              <q-item-section>
                <q-item-label class="monospace-sm">
                  {{ group.address }}::particles::{{ typeGroup.type }}
                </q-item-label>
              </q-item-section>
            </q-item>
            <q-item
              v-for="series in typeGroup.series"
              :key="series.id"
              :class="$style.seriesRow"
              dense
              :inset-level="0.2"
            >
              <q-item-section>
                <div class="items-center no-wrap q-gutter-x-sm row">
                  <span class="monospace-sm" :class="$style.seriesField">{{ series.field }}</span>
                  <q-input
                    v-model="series.label"
                    :class="$style.labelInput"
                    dense
                    outlined
                    placeholder="Label"
                  />
                  <q-btn
                    dense
                    flat
                    :icon="icons.cancel"
                    round
                    size="9px"
                    @click="removeSeries(series.id)"
                  />
                </div>
              </q-item-section>
            </q-item>
          </template>
        </template>
      </q-list>

      <div class="q-mt-md q-pb-xs">
        <common-text variant="th">Manual Entry</common-text>
      </div>
      <div class="column q-gutter-y-sm">
        <workspace-address-select v-model="manualAddress" />
        <particle-type-select v-model="manualType" :address="manualResolvedAddress" />
        <div class="items-center no-wrap q-gutter-x-sm row">
          <particle-field-select
            v-model="manualField"
            :address="manualResolvedAddress"
            class="col"
            :particle-type="manualType"
          />
          <q-input v-model="manualLabel" class="col" clearable dense label="Label" outlined />
          <schema-form-node-add-button @click="addManualEntry" />
        </div>
      </div>
    </template>
  </div>
</template>

<style module>
:global(.q-item).groupHeader {
  padding-left: 8px;
}

/* Qualified to outrank the dense item's own min-height, matching the tree's row height. */
:global(.q-item).seriesRow {
  min-height: 24px;
  padding-top: 2px;
  padding-bottom: 2px;
}

/* Holds a common left edge for the label inputs across rows. */
.seriesField {
  min-width: 160px;
}

/* Sized so the field name keeps the row and the label reads as its annotation. */
.labelInput {
  width: 180px;
}

.labelInput :global(.q-field__control),
.labelInput :global(.q-field__marginal) {
  height: 24px;
  min-height: 24px;
}

.labelInput :global(.q-field__native) {
  min-height: 24px;
  padding-top: 0;
  padding-bottom: 0;
}
</style>
