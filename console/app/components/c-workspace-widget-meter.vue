<script lang="ts" setup>
import { useElementSize } from '@vueuse/core'
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { useLatestParticle } from '@/particle-data'
import { connectionLabel, fieldUnit } from '@/particle-types'
import { formatParticleValue, particleFieldValue, thresholdLevel } from '@/particle-values'
import { displayDuration, parseDuration, useTime, utc } from '@/time'
import { useWorkspace } from '@/workspace'
import type { MeterWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MeterWidget
}>()

const emit = defineEmits<{
  /** The empty meter's "Choose Data" asks for the settings that choose it. */
  settingsRequested: []
}>()

const engine = useEngine()
const time = useTime()
const workspace = useWorkspace()

const address = $computed(
  () => workspace.resolveAddress(widget.particleAddress)?.toString() ?? null,
)

/** A connection chosen from the prompt by someone who cannot edit the workspace, which holds for
this view alone. */
let chosen = $ref<string | null>(null)

const connection = $computed(() => widget.particleConnection ?? chosen)

/** The connections the type is known to carry, from its declaration and from the records this
meter has seen, since an unnarrowed meter learns of a second one only when it arrives. */
const declared = $computed(() => {
  if (address == null || widget.particleType == null) {
    return []
  }

  return (
    engine.components.get(address)?.particles.find((type) => type.type === widget.particleType)
      ?.connections ?? []
  )
})

let seen = $ref<string[]>([])

const particle = $(
  useLatestParticle(() => ({
    address,
    type: widget.particleType ?? null,
    connection,
  })).particle,
)

watch(
  () => [address, widget.particleType, connection],
  () => (seen = []),
)

watch(
  () => particle?.connection,
  (name) => {
    if (connection == null && name != null && !seen.includes(name)) {
      seen = [...seen, name]
    }
  },
)

/** The connections to choose between, set only while the meter would blend several. */
const choices = $computed(() => {
  if (connection != null) {
    return []
  }

  const names = [...new Set([...declared, ...seen])]
  return names.length > 1 ? names : []
})

function choose(name: string) {
  if (workspace.canEdit) {
    widget.particleConnection = name
  } else {
    chosen = name
  }
}

const textWeight = $computed(() => {
  switch (widget.fontWeight) {
    case 'slim':
      return 200
    case 'normal':
      return 300
    case 'bold':
      return 'bold'
    default:
      return 400
  }
})

const value = $computed(() =>
  particle == null ? undefined : particleFieldValue(particle, widget.particleField),
)

const declaredUnit = $computed(() => {
  const types = address == null ? [] : (engine.components.get(address)?.particles ?? [])
  return fieldUnit(types, widget.particleType, widget.particleField)
})

/** The unit after the value: the setting, or the unit the field declares. */
const unit = $computed(() => widget.unit?.trim() || declaredUnit || '')

const display = $computed(() => {
  if (particle == null) {
    return ''
  }

  const read = formatParticleValue(value, widget.decimals)
  return `${widget.prefix ?? ''}${read}${unit === '' ? '' : ` ${unit}`}${widget.suffix ?? ''}`
})

const level = $computed(() => thresholdLevel(value, widget))

const age = $computed(() =>
  particle == null ? null : time.nowFast.diff(utc(particle.timestamp), 'millisecond'),
)

const staleAfter = $computed(() => {
  try {
    return widget.staleAfter == null ? null : parseDuration(widget.staleAfter).asMilliseconds()
  } catch {
    return null
  }
})

const isStale = $computed(() => age != null && staleAfter != null && age > staleAfter)

const updatedAt = $computed(() => {
  if (age == null) {
    return ''
  }

  return age < 1500 ? 'Now' : `${displayDuration(age / 1000, { decimals: 0, short: true })} ago`
})

let box = $ref<HTMLElement | null>(null)
let sample = $ref<HTMLElement | null>(null)

const { width: boxWidth, height: boxHeight } = useElementSize(() => box)
const { width: sampleWidth, height: sampleHeight } = useElementSize(() => sample)

/** The size the text is drawn at, the setting or else the largest that fits the box, read from
the text drawn once at `sampleSize` out of sight. */
const sampleSize = 100
const fontSize = $computed(() => {
  if (widget.fontSize != null) {
    return widget.fontSize
  }

  if (sampleWidth.value === 0 || sampleHeight.value === 0) {
    return 18
  }

  // The age line takes the bottom of the box, so the value keeps clear of it.
  const scale = Math.min(
    (boxWidth.value * 0.9) / sampleWidth.value,
    (boxHeight.value * 0.75) / sampleHeight.value,
  )
  return Math.max(8, Math.floor(sampleSize * scale))
})
</script>

<template>
  <div
    v-if="widget.particleType == null"
    class="flex min-h-full flex-1 items-center justify-center"
  >
    <c-tooltip text="Choose Data">
      <c-button
        aria-label="Choose Data"
        class="rounded-full"
        color="primary"
        :icon="icons.add"
        @click="emit('settingsRequested')"
      />
    </c-tooltip>
  </div>
  <!-- A value blended from several sources would mislead, so the meter asks which to show. -->
  <div
    v-else-if="choices.length > 0"
    class="flex min-h-full flex-1 flex-col items-center justify-center gap-2 p-2"
  >
    <c-text variant="description">Choose a connection</c-text>
    <div class="flex flex-wrap justify-center gap-1">
      <c-button
        v-for="name in choices"
        :key="name"
        color="neutral"
        :label="address == null ? name : connectionLabel(engine, address, name)"
        size="xs"
        variant="outline"
        @click="choose(name)"
      />
    </div>
  </div>
  <div
    v-else
    ref="box"
    class="relative flex h-full min-h-full flex-1 items-center justify-center overflow-hidden"
  >
    <!-- The text at a known size, out of sight, which the fitted size scales from. -->
    <span
      ref="sample"
      aria-hidden="true"
      class="invisible absolute whitespace-pre"
      :style="{ fontSize: `${sampleSize}px`, fontWeight: textWeight }"
    >
      {{ display || ' ' }}
    </span>
    <div
      class="m-0 p-0 text-center whitespace-pre transition-opacity"
      :class="[
        level === 'error' && 'text-error',
        level === 'warning' && 'text-warning',
        isStale && 'opacity-40',
      ]"
      data-meter-value
      :style="{ fontSize: `${fontSize}px`, fontWeight: textWeight }"
    >
      {{ display || ' ' }}
    </div>
    <div
      class="absolute right-1 bottom-0.5 text-[10px]"
      :class="isStale ? 'text-warning' : 'opacity-50'"
      data-meter-age
    >
      {{ updatedAt }}
    </div>
  </div>
</template>
