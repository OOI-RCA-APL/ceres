<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'

import { useEngine } from '@/api/engine'
import { defaultSeriesColor } from '@/chart'
import icons from '@/icons'
import { duplicateParticleGroup, groupConnection, removeParticleSeries } from '@/particle-series'
import { connectionLabel, useParticleTypesByAddress } from '@/particle-types'
import { ChartWidgetSeriesTypeModel } from '@/workspace'
import type { ChartWidgetParticle, ChartWidgetSeries, ChartWidgetSeriesType } from '@/workspace'

/** The series a chart draws, grouped by the component and type they read, each with its label,
line type and color. */
let modelValue = $(defineModel<ChartWidgetParticle[]>({ default: () => [] }))

const engine = useEngine()

type SelectedTypeGroup = {
  type: string
  connection: string | null
  /** Where the group sits in the model, for the actions that act on the whole group. */
  index: number
  series: ChartWidgetSeries[]
  warning: string | null
}
type SelectedAddressGroup = { address: string; types: SelectedTypeGroup[] }

const declaredByAddress = $(
  useParticleTypesByAddress(() =>
    modelValue.flatMap((particle) => particle.address?.toString() ?? []),
  ).types,
)

/** Why a stored series names something the components do not declare, if it does.

A driver rename leaves the series behind pointing at a type nothing produces, and the chart
then draws an empty plot with nothing on screen saying why.
*/
function seriesWarning(address: string, type: string): string | null {
  // Nothing is known before the component list lands, which is not the same as nothing existing.
  if (engine.components.all.length === 0) {
    return null
  }

  const declared = declaredByAddress.get(address)
  if (declared == null || engine.components.get(address) == null) {
    return `No component at ${address}.`
  }

  if (!declared.some((current) => current.type === type)) {
    return `${address} declares no particle type "${type}".`
  }

  return null
}

// Grouped for display under the address and type the picker uses, merging any stored entries
// that happen to share an address and type rather than assuming one entry per pair.
const selectedGroups = $computed<SelectedAddressGroup[]>(() => {
  const byAddress = new Map<string, Map<string, SelectedTypeGroup>>()

  for (const [index, particle] of modelValue.entries()) {
    const address = particle.address?.toString() ?? '(no address)'
    const type = particle.type ?? '(no type)'
    const connection = groupConnection(particle)
    const byType = byAddress.get(address) ?? new Map<string, SelectedTypeGroup>()

    // Narrowing to a connection is what separates two groups of the same type, so it belongs
    // in the key rather than merging them back into one row.
    const key = `${type}|${connection ?? ''}`
    const existing = byType.get(key)
    byType.set(key, {
      type,
      connection,
      index: existing?.index ?? index,
      series: [...(existing?.series ?? []), ...particle.series],
      warning: seriesWarning(address, type),
    })
    byAddress.set(address, byType)
  }

  return [...byAddress.entries()].map(([address, byType]) => ({
    address,
    types: [...byType.values()],
  }))
})

function groupItems(group: SelectedTypeGroup): DropdownMenuItem[] {
  return [
    {
      label: 'Duplicate Group',
      icon: icons.duplicate,
      onSelect: () => (modelValue = duplicateParticleGroup(modelValue, group.index)),
    },
  ]
}

// What the chart draws this series in. A widget stored before series carried a color has none to
// show, and the swatch must still stand for the line it edits.
function colorOf(series: ChartWidgetSeries): string {
  if (series.color != null) {
    return series.color
  }

  const drawn = modelValue.flatMap((particle) => particle.series)
  return defaultSeriesColor(Math.max(0, drawn.indexOf(series)))
}

function removeSeries(seriesId: string) {
  modelValue = removeParticleSeries(modelValue, seriesId)
}
</script>

<template>
  <div class="border-default rounded-md border pb-1">
    <div v-if="selectedGroups.length === 0" class="px-2 py-1">
      <c-text variant="description">No particle series selected.</c-text>
    </div>
    <template v-for="group in selectedGroups" :key="group.address">
      <template
        v-for="typeGroup in group.types"
        :key="`${group.address}|${typeGroup.type}|${typeGroup.connection ?? ''}`"
      >
        <!-- The established path notation, one line standing in for the address and type
        levels. -->
        <div class="flex items-center gap-1.5 px-2 py-1">
          <c-text variant="mono-sm">{{ group.address }}::particles::{{ typeGroup.type }}</c-text>
          <!-- The picker chooses the connection, so the list only names it. -->
          <c-badge
            v-if="typeGroup.connection != null"
            color="neutral"
            :label="connectionLabel(engine, group.address, typeGroup.connection)"
            size="sm"
            variant="subtle"
          />
          <c-tooltip v-if="typeGroup.warning != null" :text="typeGroup.warning">
            <c-icon class="text-warning shrink-0" :name="icons.warning" size="14" />
          </c-tooltip>
          <div class="grow" />
          <c-dropdown-menu :items="groupItems(typeGroup)" size="sm">
            <c-button color="neutral" :icon="icons.more" size="xs" square variant="ghost" />
          </c-dropdown-menu>
        </div>
        <div
          v-for="series in typeGroup.series"
          :key="series.id"
          class="flex min-h-6 items-center gap-2 py-0.5 pr-2 pl-5"
        >
          <span class="min-w-28 font-mono text-[11px]">{{ series.field }}</span>
          <input
            v-model="series.label"
            :class="[
              'border-default focus:border-primary w-45 rounded-sm border',
              'bg-transparent px-1.5 py-0.5 text-xs outline-none',
            ]"
            placeholder="Label"
            spellcheck="false"
            type="text"
          />
          <div class="grow" />
          <c-tooltip text="Series Type">
            <c-select
              class="w-24 shrink-0"
              :items="[...ChartWidgetSeriesTypeModel.options]"
              :model-value="series.type"
              size="xs"
              variant="ghost"
              @update:model-value="(value: ChartWidgetSeriesType) => (series.type = value)"
            />
          </c-tooltip>
          <c-tooltip text="Series Color">
            <c-color-input
              :model-value="colorOf(series)"
              @update:model-value="series.color = $event"
            />
          </c-tooltip>
          <c-button
            color="neutral"
            :icon="icons.cancel"
            size="xs"
            square
            variant="ghost"
            @click="removeSeries(series.id)"
          />
        </div>
      </template>
    </template>
  </div>
</template>
