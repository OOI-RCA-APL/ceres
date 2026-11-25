<script lang="ts" setup>
import icons from '@/icons'
import { useTime, utc } from '@/time'
import {
  boundsOf,
  calendarDay,
  type CalendarDay,
  calendarRange,
  describeRange,
  fixedRange,
  lengthOf,
  liveRange,
  pageRange,
  timeRangePresets,
  type TimeRange,
} from '@/time-range'

let range = $(defineModel<TimeRange>({ required: true }))

const time = useTime()

const isLive = $computed(() => range.mode === 'live')

function page(direction: -1 | 1) {
  range = pageRange(range, direction, time.now.valueOf())
}

// Pausing holds what is on screen, and resuming follows new data over the same length.
function toggleLive() {
  if (range.mode === 'live') {
    const { start, end } = boundsOf(range, time.now.valueOf())
    range = fixedRange(start, end) ?? range
  } else {
    range = liveRange(lengthOf(range))
  }
}

let isOpen = $ref(false)

const inputFormat = 'YYYY-MM-DD HH:mm:ss'
const inputFormats = [inputFormat, 'YYYY-MM-DD HH:mm', 'YYYY-MM-DD']

// The popover edits a draft, applied only on "Apply", so a half-typed range never reloads data.
let draftStart = $ref('')
let draftEnd = $ref('')

function startDraft() {
  const { start, end } = boundsOf(range, time.now.valueOf())
  draftStart = utc(start).format(inputFormat)
  draftEnd = utc(end).format(inputFormat)
}

function parsed(text: string): number {
  const value = utc(text.trim(), inputFormats, true)
  return value.isValid() ? value.valueOf() : Number.NaN
}

/** The range the draft names, or null while it names none. */
function draftRange(): TimeRange | null {
  return fixedRange(parsed(draftStart), parsed(draftEnd))
}

const isDraftValid = $computed(() => draftRange() != null)

/** The calendar's selection, the UTC days the draft covers, its end exclusive in the draft and
inclusive on the calendar. */
const draftDays = $computed(() => {
  const draft = draftRange()
  if (draft == null || draft.mode !== 'fixed') {
    return undefined
  }

  return { start: calendarDay(draft.start), end: calendarDay(draft.end - 1) }
})

function pickDays(days: { start?: CalendarDay; end?: CalendarDay } | null) {
  if (days?.start == null || days.end == null) {
    return
  }

  const picked = calendarRange(days.start, days.end)
  if (picked?.mode === 'fixed') {
    draftStart = utc(picked.start).format(inputFormat)
    draftEnd = utc(picked.end).format(inputFormat)
  }
}

function applyDraft() {
  const draft = draftRange()
  if (draft != null) {
    range = draft
    isOpen = false
  }
}

function choosePreset(span: number) {
  range = liveRange(span)
  isOpen = false
}
</script>

<template>
  <div class="flex items-center gap-0.5">
    <c-tooltip text="Earlier">
      <c-button
        aria-label="Earlier"
        color="neutral"
        :icon="icons.chevronLeft"
        size="xs"
        square
        variant="ghost"
        @click="page(-1)"
      />
    </c-tooltip>
    <c-popover
      v-model:open="isOpen"
      :ui="{ content: 'p-2' }"
      @update:open="(open: boolean) => open && startDraft()"
    >
      <c-button color="neutral" :label="describeRange(range)" size="xs" variant="ghost" />
      <template #content>
        <div class="flex gap-3">
          <div class="flex flex-col gap-0.5">
            <c-button
              v-for="preset in timeRangePresets"
              :key="preset.label"
              color="neutral"
              :label="`Last ${preset.label}`"
              size="xs"
              :variant="isLive && lengthOf(range) === preset.span ? 'soft' : 'ghost'"
              @click="choosePreset(preset.span)"
            />
          </div>
          <div class="flex w-64 flex-col gap-2">
            <c-calendar :model-value="draftDays" range size="xs" @update:model-value="pickDays" />
            <c-form-field label="Start">
              <c-input v-model="draftStart" class="w-full" size="xs" />
            </c-form-field>
            <c-form-field label="End">
              <div class="flex gap-1">
                <c-input v-model="draftEnd" class="w-full" size="xs" />
                <c-button
                  color="neutral"
                  label="Now"
                  size="xs"
                  variant="outline"
                  @click="draftEnd = utc(time.now).format(inputFormat)"
                />
              </div>
            </c-form-field>
            <c-text v-if="!isDraftValid" class="text-error" variant="description">
              The end must come after the start, both as YYYY-MM-DD HH:mm:ss in UTC.
            </c-text>
            <c-button block :disabled="!isDraftValid" label="Apply" size="xs" @click="applyDraft" />
          </div>
        </div>
      </template>
    </c-popover>
    <c-tooltip text="Later">
      <c-button
        aria-label="Later"
        color="neutral"
        :disabled="isLive"
        :icon="icons.chevronRight"
        size="xs"
        square
        variant="ghost"
        @click="page(1)"
      />
    </c-tooltip>
    <slot />
    <c-tooltip :text="isLive ? 'Pause' : 'Follow New Data'">
      <c-button
        :color="isLive ? 'primary' : 'neutral'"
        label="Live"
        size="xs"
        :variant="isLive ? 'soft' : 'ghost'"
        @click="toggleLive"
      />
    </c-tooltip>
  </div>
</template>
