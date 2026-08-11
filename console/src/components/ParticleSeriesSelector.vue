<script lang="ts" setup>
import { Address, AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import ParticleFieldSelect from '@/components/ParticleFieldSelect.vue'
import ParticleSeriesSelectorAddress from '@/components/ParticleSeriesSelectorAddress.vue'
import ParticleTypeSelect from '@/components/ParticleTypeSelect.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import {
  ChartWidgetParticle,
  ChartWidgetParticleModel,
  ChartWidgetSeries,
  ChartWidgetSeriesModel,
  useWorkspace,
} from '@/workspace'

const { address: pinnedAddress, showSelected = false } = defineProps<{
  /** Fixes the tree to this one address rather than a workspace's placement subtree, the
  component page's case. */
  address?: string | null
  /** Whether the "Selected Particle Series" section renders below the tree. Requires a
  workspace context, so only a host without a pinned address sets this. */
  showSelected?: boolean
}>()

let modelValue = $(defineModel<ChartWidgetParticle[]>({ required: true }))

const engine = useEngine()

// Not called when the address is pinned, since the component page hosts this outside any
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

function findParticleIndex(particles: ChartWidgetParticle[], address: string, type: string) {
  return particles.findIndex(
    (particle) => (particle.address?.toString() ?? null) === address && particle.type === type
  )
}

/** Turn `field` on or off for `address`'s `type`, merging into that pair's existing entry or
removing it once its last field goes off. */
function toggleField(address: string, type: string, field: string, value: boolean) {
  const particles = [...modelValue]
  const index = findParticleIndex(particles, address, type)

  if (value) {
    if (index === -1) {
      particles.push(
        ChartWidgetParticleModel.parse({
          address: new AddressSelector(address),
          type,
          series: [{ field }],
        })
      )
    } else if (!particles[index].series.some((series) => series.field === field)) {
      particles[index] = {
        ...particles[index],
        series: [...particles[index].series, ChartWidgetSeriesModel.parse({ field })],
      }
    }
  } else if (index !== -1) {
    const series = particles[index].series.filter((series) => series.field !== field)
    if (series.length === 0) {
      particles.splice(index, 1)
    } else {
      particles[index] = { ...particles[index], series }
    }
  }

  modelValue = particles
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
  modelValue = modelValue
    .map((particle) => ({
      ...particle,
      series: particle.series.filter((series) => series.id !== seriesId),
    }))
    .filter((particle) => particle.series.length > 0)
}

let manualAddress = $ref<string | null>(null)
let manualType = $ref<string | null>(null)
let manualField = $ref<string | null>(null)
let manualLabel = $ref<string | null>(null)

const manualResolvedAddress = $computed(
  () => workspace?.resolveAddress(manualAddress)?.toString() ?? manualAddress
)

/** Add a manual entry for an undeclared type or field, merging into an existing address/type
entry the way a toggle does. Only the field and label reset, so adding several fields for the
same address and type does not require reselecting either. */
function addManualEntry() {
  if (manualAddress == null || manualType == null || manualField == null) {
    return
  }

  const address = manualResolvedAddress
  if (address == null) {
    return
  }

  const particles = [...modelValue]
  const index = findParticleIndex(particles, address, manualType)
  const series = ChartWidgetSeriesModel.parse({ field: manualField, label: manualLabel })

  if (index === -1) {
    particles.push(
      ChartWidgetParticleModel.parse({
        address: new AddressSelector(address),
        type: manualType,
        series: [series],
      })
    )
  } else {
    particles[index] = { ...particles[index], series: [...particles[index].series, series] }
  }

  modelValue = particles
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
        :default-opened="addressNodes.length === 1"
        :particles="modelValue"
        @toggle="(type, field, value) => toggleField(node.toString(), type, field, value)"
      />
    </q-list>

    <template v-if="showSelected">
      <div class="q-pt-md q-px-sm">
        <common-text variant="th">Selected Particle Series</common-text>
      </div>
      <div class="column q-gutter-sm q-pa-sm">
        <q-card v-if="selectedGroups.length === 0" bordered flat>
          <div class="q-pa-sm text-grey-6">No particle series selected.</div>
        </q-card>
        <q-card v-for="group in selectedGroups" :key="group.address" bordered flat>
          <div class="column q-gutter-xs q-pa-sm">
            <common-text variant="th">{{ group.address }}</common-text>
            <div
              v-for="typeGroup in group.types"
              :key="typeGroup.type"
              class="column q-gutter-xs q-pl-sm"
            >
              <common-text class="text-grey-7" variant="description">
                {{ typeGroup.type }}
              </common-text>
              <div
                v-for="series in typeGroup.series"
                :key="series.id"
                class="items-center q-gutter-xs row"
              >
                <div class="col-grow">{{ series.field }}</div>
                <div class="col-grow">
                  <schema-form-value
                    v-model="series.label"
                    :schema="{ type: 'string', title: 'Label', optional: true }"
                  />
                </div>
                <q-btn
                  dense
                  flat
                  :icon="icons.cancel"
                  round
                  size="9px"
                  @click="removeSeries(series.id)"
                />
              </div>
            </div>
          </div>
        </q-card>

        <q-card bordered flat>
          <div class="column q-gutter-xs q-pa-sm">
            <common-text variant="th">Manual Entry</common-text>
            <workspace-address-select v-model="manualAddress" />
            <particle-type-select v-model="manualType" :address="manualResolvedAddress" />
            <div class="items-center q-gutter-xs row">
              <div class="col-grow">
                <particle-field-select
                  v-model="manualField"
                  :address="manualResolvedAddress"
                  :particle-type="manualType"
                />
              </div>
              <div class="col-grow">
                <schema-form-value
                  v-model="manualLabel"
                  :schema="{ type: 'string', title: 'Label', optional: true }"
                />
              </div>
              <schema-form-node-add-button @click="addManualEntry" />
            </div>
          </div>
        </q-card>
      </div>
    </template>
  </div>
</template>
