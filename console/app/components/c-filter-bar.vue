<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { nextTick, provide } from 'vue'

import { useDialogs } from '@/dialogs'
import {
  defaultTextKind,
  definitionsFor,
  getFilterDefinition,
  matchDefinitions,
} from '@/filters/definitions'
import type { FilterDefinition, FilterValueInput, RecordKind } from '@/filters/definitions'
import { filterLiftKey } from '@/filters/lift'
import {
  createBlock,
  createCondition,
  isBlock,
  withAppendedTo,
  withBlockOp,
  withConditionValue,
  withGrouped,
  withMovedToRoot,
  withoutItems,
} from '@/filters/model'
import type { FilterItem, FilterQuery } from '@/filters/model'
import { createFilterSelection } from '@/filters/selection'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import type { SelectMode } from '@/workspace'

const {
  recordKind,
  addressOptions = [],
  connectionOptions = [],
} = defineProps<{
  recordKind: RecordKind
  /** The choices an address condition offers, from the hosting view's scope. */
  addressOptions?: readonly string[]
  /** The connection names the hosting view's scope declares, offered the same way. */
  connectionOptions?: readonly string[]
}>()

let query = $(defineModel<FilterQuery>({ required: true }))

const selection = createFilterSelection({
  query: () => query,
  recordKind: () => recordKind,
  onUpdate: (updated) => {
    query = updated
  },
})

const selectedIds = $(selection.selectedIds)

let rootElement = $ref<HTMLElement | null>(null)
let inputElement = $ref<HTMLInputElement | null>(null)

/** What the bar's own input holds, matched against the registry as it grows. */
let search = $ref('')
let isInputFocused = $ref(false)

/** The row the arrow keys stand on in the suggestion list. */
let highlighted = $ref(0)

/** The condition whose value input claims focus, the one just accepted. */
let focusId = $ref<string | null>(null)

const suggestions = $computed(() => matchDefinitions(definitionsFor(recordKind), search))

/** The record kind's own text search, offered with the text as typed.

Listed alongside the fields so searching for a phrase is a visible choice rather than what
happens only when the phrase resembles no field name.
*/
const freeTextDefinition = $computed(() => {
  if (search.trim() === '') {
    return null
  }

  return getFilterDefinition(defaultTextKind(recordKind))
})

/** The grouping an operator typed into the bar would make, which nothing else can express.

Offered above the fields because a word that is exactly `and` or `or` is being typed as the
operator, no field being named that.
*/
const groupingOperator = $computed<'and' | 'or' | null>(() => {
  const typed = search.trim().toLowerCase()
  return typed === 'and' || typed === 'or' ? typed : null
})

/** An address is written with or without its leading marker, so both are matched the same. */
function withoutMarker(value: string): string {
  return value.startsWith('@') ? value.slice(1) : value
}

/** How much must be typed before values are offered, since a single letter is in most of them
and the fields would be buried under the matches. */
const minimumValueSearch = 2

/** The most values offered at once, so a common substring cannot fill the list. */
const maximumValueSuggestions = 8

type ValueSuggestion = { definition: FilterDefinition; value: string }

/** How a value's type reads in the list. The input types naming how a value is picked rather
than what it is show as the string they store. */
function typeLabel(input: FilterValueInput): string {
  return input.type === 'address' || input.type === 'connection' ? 'str' : input.type
}

/** The values a definition can be given outright, wherever the console knows them. */
function valuesFor(definition: FilterDefinition): readonly string[] {
  if (definition.input.type === 'enum') {
    return definition.input.options
  }
  if (definition.input.type === 'address') {
    return addressOptions
  }

  return definition.kind === 'connection' ? connectionOptions : []
}

/** What a definition answers to, its own label included. */
function termsFor(definition: FilterDefinition): string[] {
  return [definition.label.toLowerCase(), ...definition.aliases]
}

/** A condition written out in full, a field named at the head and its value in the rest.

`connection contains contr` says the whole thing, so it is offered whole. The longest name
matched wins, since `connection` opens both `Connection` and `Connection Contains` and only the
words after it say which was meant.
*/
function qualifiedValues(): ValueSuggestion[] {
  const typed = search.trim()
  const lowered = typed.toLowerCase()

  const matched: { definition: FilterDefinition; value: string; named: number }[] = []
  for (const definition of definitionsFor(recordKind)) {
    const term = termsFor(definition)
      .filter((candidate) => lowered.startsWith(`${candidate} `))
      .sort((first, second) => second.length - first.length)[0]
    if (term == null) {
      continue
    }

    const rest = typed.slice(term.length).trim()
    if (rest === '') {
      continue
    }

    const known = valuesFor(definition)
    const wanted = withoutMarker(rest.toLowerCase())
    const found = known.filter((value) => withoutMarker(value.toLowerCase()).includes(wanted))
    for (const value of found) {
      matched.push({ definition, value, named: term.length })
    }

    // Taken as typed where the value is free text, so a name the engine is not carrying right
    // now still filters. An enum accepts only what it declares, so it is left alone.
    if (found.length === 0 && definition.input.type !== 'enum') {
      matched.push({ definition, value: rest, named: term.length })
    }
  }

  return matched
    .sort((first, second) => second.named - first.named)
    .map(({ definition, value }) => ({ definition, value }))
}

/** The known values the typed text names outright, prefix matches first. */
function knownValues(): ValueSuggestion[] {
  const typed = withoutMarker(search.trim().toLowerCase())
  if (typed.length < minimumValueSearch) {
    return []
  }

  const matched: { definition: FilterDefinition; value: string; leads: boolean }[] = []
  for (const definition of definitionsFor(recordKind)) {
    for (const value of valuesFor(definition)) {
      const candidate = withoutMarker(value.toLowerCase())
      if (candidate.includes(typed)) {
        matched.push({ definition, value, leads: candidate.startsWith(typed) })
      }
    }
  }

  return [
    ...matched.filter((match) => match.leads),
    ...matched.filter((match) => !match.leads),
  ].map(({ definition, value }) => ({ definition, value }))
}

/** The conditions the typed words name, offered so saying one is not two steps.

A field written out with its value comes first, that being the whole condition spelled out,
and a bare value follows.
*/
const valueSuggestions = $computed<ValueSuggestion[]>(() => {
  const key = (suggestion: ValueSuggestion) => `${suggestion.definition.kind}=${suggestion.value}`
  const qualified = qualifiedValues()
  const named = new Set(qualified.map(key))

  return [...qualified, ...knownValues().filter((suggestion) => !named.has(key(suggestion)))].slice(
    0,
    maximumValueSuggestions,
  )
})

const groupingCount = $computed(() => (groupingOperator == null ? 0 : 1))

/** The text search leads, being the safe reading of any words at all, with the conditions they
name underneath and the bare fields last. */
const freeTextIndex = $computed(() => (freeTextDefinition == null ? -1 : groupingCount))
const valuesOffset = $computed(() => groupingCount + (freeTextDefinition == null ? 0 : 1))
const fieldsOffset = $computed(() => valuesOffset + valueSuggestions.length)
const suggestionCount = $computed(() => fieldsOffset + suggestions.length)
const isSuggesting = $computed(() => isInputFocused && suggestionCount > 0)

/** The row Tab takes, which is the one under a leading text search.

Typing a value the console knows leaves the text search on top, that being the safer reading of
words nothing else matched. Tab takes the reading underneath it without moving off Enter.
*/
const tabRow = $computed(() => (freeTextIndex === 0 && suggestionCount > 1 ? 1 : -1))

/** The group conditions are being added to, set by typing its operator and left behind on the
first click away, so `Address and Level` builds one group rather than three loose chips. */
let openBlockId = $ref<string | null>(null)

/** Group the condition to the left under `op`, or start an empty group when there is none.

An operator typed against a group that already joins by it reopens that group rather than nesting
a second one inside, which would read the same and draw a box around a box.
*/
function acceptGrouping(op: 'and' | 'or') {
  const last = query[query.length - 1]
  search = ''
  highlighted = 0

  if (last != null && isBlock(last) && last.op === op) {
    openBlockId = last.id
    return
  }

  const block = createBlock(op, last == null ? [] : [last])
  query = [...(last == null ? query : query.slice(0, -1)), block]
  openBlockId = block.id
}

/** Put `item` in the group being built, or at the end of the bar when there is none. */
function append(item: FilterItem) {
  if (openBlockId == null) {
    query = [...query, item]
    return
  }

  query = withAppendedTo(query, openBlockId, item)
}

function accept(definition: FilterDefinition) {
  const condition = createCondition(definition.kind, null)
  append(condition)
  search = ''
  highlighted = 0
  focusId = condition.id
}

function acceptFreeText() {
  const condition = createCondition(defaultTextKind(recordKind), search.trim())
  append(condition)
  search = ''
  highlighted = 0
  focusId = condition.id
}

// The condition arrives with its value already, so focus stays in the bar rather than moving
// into a picker offering the choice that was just made.
function acceptValue(suggestion: ValueSuggestion) {
  append(createCondition(suggestion.definition.kind, suggestion.value))
  search = ''
  highlighted = 0
}

/** Take the row under a leading text search, leaving Tab to move focus when there is none. */
function onTab(event: KeyboardEvent) {
  if (tabRow < 0) {
    return
  }

  const suggested = valueSuggestions[tabRow - valuesOffset]
  const definition = suggestions[tabRow - fieldsOffset]
  if (suggested == null && definition == null) {
    return
  }

  event.preventDefault()
  if (suggested != null) {
    acceptValue(suggested)
  } else if (definition != null) {
    accept(definition)
  }
}

function onEnter() {
  if (search.trim() === '') {
    return
  }

  if (groupingOperator != null && highlighted === 0) {
    acceptGrouping(groupingOperator)
    return
  }

  // The text search when it is the highlighted row, and otherwise the ranked field match. Text
  // resembling no field at all leaves nothing else to take.
  if (highlighted === freeTextIndex) {
    acceptFreeText()
    return
  }

  const suggested = valueSuggestions[highlighted - valuesOffset]
  if (suggested != null) {
    acceptValue(suggested)
    return
  }

  const definition = suggestions[highlighted - fieldsOffset]
  if (definition != null) {
    accept(definition)
    return
  }

  // Nothing sits on the highlighted row, so the text search, or the ranked field match where
  // there is no text to search for.
  if (freeTextDefinition != null) {
    acceptFreeText()
  } else if (suggestions[0] != null) {
    accept(suggestions[0])
  }
}

function onInputBackspace() {
  if (search === '' && query.length > 0) {
    query = query.slice(0, -1)
  }
}

/** Focus flows back to the bar's input once a value is finished, keeping typing continuous. */
async function onCommit() {
  focusId = null
  await nextTick()
  inputElement?.focus()
}

function onChange(id: string, value: unknown) {
  query = withConditionValue(query, id, value)
}

function onRemove(id: string) {
  query = withoutItems(query, new Set([id]))
}

function onOperator(id: string, op: 'and' | 'or') {
  query = withBlockOp(query, id, op)
}

function modeOf(event: MouseEvent): SelectMode {
  if (event.shiftKey) {
    return 'extend'
  }

  return event.metaKey || event.ctrlKey ? 'toggle' : 'replace'
}

function onChipClick(id: string, event: MouseEvent) {
  if (reorder.consumeClick()) {
    return
  }

  openBlockId = null

  selection.select(id, modeOf(event))

  // Clicking a condition is reaching for its value, so the caret lands in it wherever on the chip
  // the click fell. Extending a selection is not, several conditions having no one value to edit.
  if (modeOf(event) === 'replace') {
    const chip = event.currentTarget as HTMLElement | null
    chip
      ?.querySelector<HTMLElement>(
        'input, textarea, select, [role="combobox"], [contenteditable="true"]',
      )
      ?.focus()
  }
}

function onBarKeydown(event: KeyboardEvent) {
  const field =
    event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement
      ? event.target
      : null

  // Clicking a condition puts the caret in its value, so the clipboard keys have to reach the bar
  // from inside a field. They act on whole conditions when the field has nothing of its own in
  // hand, and on the text otherwise.
  if (event.metaKey || event.ctrlKey) {
    const hasSelectedText = field != null && field.selectionStart !== field.selectionEnd

    if (event.key === 'c' && !hasSelectedText) {
      selection.copySelected()
    } else if (event.key === 'x' && !hasSelectedText) {
      selection.cutSelected()
    } else if (event.key === 'v' && (field == null || field.value === '')) {
      selection.paste()
      event.preventDefault()
    }

    return
  }

  // What is left edits the bar itself, which a field being typed into owns instead.
  if (field != null) {
    return
  }

  if (event.key === 'Delete' || event.key === 'Backspace') {
    selection.removeSelected()
    event.preventDefault()
  } else if (event.key === 'Escape') {
    selection.clear()
  }
}

const contextMenuItems = $computed<DropdownMenuItem[][]>(() => {
  const single = selectedIds.size === 1 ? query.find((item) => selectedIds.has(item.id)) : null

  const grouping: DropdownMenuItem[] = []
  if (selectedIds.size > 1) {
    grouping.push(
      { label: 'Group as OR', onSelect: () => selection.groupSelected('or') },
      { label: 'Group as AND', onSelect: () => selection.groupSelected('and') },
    )
  }
  if (single != null && isBlock(single)) {
    grouping.push({ label: 'Ungroup', onSelect: () => selection.ungroup(single.id) })
  }

  const clipboard: DropdownMenuItem[] = [
    { label: 'Copy', icon: icons.copy, onSelect: () => selection.copySelected() },
    { label: 'Cut', icon: icons.cut, onSelect: () => selection.cutSelected() },
    {
      label: 'Paste',
      icon: icons.paste,
      disabled: !selection.canPaste(),
      onSelect: () => selection.paste(),
    },
  ]

  const removal: DropdownMenuItem[] = [
    { label: 'Remove', icon: icons.delete, onSelect: () => selection.removeSelected() },
  ]

  return grouping.length > 0 ? [grouping, clipboard, removal] : [clipboard, removal]
})

/** Append a condition of `kind`, selected with its value input focused, the header quick filters'
path into the bar. */
function appendKind(kind: string) {
  const condition = createCondition(kind, null)
  append(condition)
  focusId = condition.id
  selection.select(condition.id, 'replace')
}

defineExpose({ appendKind })

const dialogs = useDialogs()

/** How much of a chip's width, centred, counts as dropping onto it rather than beside it.

The edges stay a reorder, so the two gestures share a row without either becoming hard to aim:
past a chip is a move, into it is a group.
*/
const groupTargetShare = 0.6

function chipElements(): HTMLElement[] {
  return [...(rootElement?.querySelectorAll<HTMLElement>('[data-filter-chip]') ?? [])]
}

/** Which chip a pointer at `x` is over the middle of, ignoring the one being dragged. */
function groupTargetAt(x: number, dragged: number): number {
  return chipElements().findIndex((chip, index) => {
    if (index === dragged) {
      return false
    }

    const box = chip.getBoundingClientRect()
    const inset = (box.width * (1 - groupTargetShare)) / 2
    return x >= box.left + inset && x <= box.right - inset
  })
}

/** The chip a release would group with, drawn as a target while one is held over it. */
let groupTargetId = $ref<string | null>(null)

function onBarPointerMove(event: PointerEvent) {
  if (!reorder.isDragging) {
    groupTargetId = null
    return
  }

  const dragged = query.findIndex((_, index) => reorder.isGrabbed(index))
  const over = groupTargetAt(event.clientX, dragged)
  groupTargetId = over === -1 ? null : (query[over]?.id ?? null)
}

function labelOf(item: FilterItem): string {
  if (isBlock(item)) {
    return `(${item.op})`
  }

  return getFilterDefinition(item.kind)?.label ?? item.kind
}

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => chipElements(),
  onDrop: (index, event) => {
    groupTargetId = null
    const over = groupTargetAt(event.clientX, index)
    const dragged = query[index]
    const onto = query[over]
    if (over === -1 || dragged == null || onto == null) {
      return false
    }

    dialogs.groupFilters([labelOf(onto), labelOf(dragged)]).onOk((op) => {
      query = withGrouped(query, new Set([onto.id, dragged.id]), op)
    })

    return true
  },
  onReorder: (from, to) => {
    const dragged = query[from]
    if (dragged == null) {
      return
    }

    // A drag of a selected chip carries the whole selection as a unit.
    if (selectedIds.has(dragged.id) && selectedIds.size > 1) {
      selection.moveSelected(to > from ? to + 1 : to)
    } else {
      query = moved([...query], from, to)
    }
  },
})

/** The condition being carried out of the block it sits in. */
let lifted = $ref<{
  id: string
  pointerId: number
  origin: number
  x: number
  moved: boolean
} | null>(null)

/** Which root position a pointer at `x` would drop into. */
function rootIndexAt(x: number): number {
  const chips = chipElements()
  const before = chips.findIndex((chip) => {
    const box = chip.getBoundingClientRect()
    return x < box.left + box.width / 2
  })

  return before === -1 ? chips.length : before
}

/** Whether a release at `event` landed back inside the block the chip came from, which asks for
nothing rather than for a move to where that block stands. */
function isOverOwnBlock(id: string, event: PointerEvent): boolean {
  const chip = rootElement?.querySelector<HTMLElement>(`[data-filter-lift="${CSS.escape(id)}"]`)
  const block = chip?.parentElement?.closest<HTMLElement>('[data-filter-block]')
  if (block == null) {
    return false
  }

  const box = block.getBoundingClientRect()
  return (
    event.clientX >= box.left &&
    event.clientX <= box.right &&
    event.clientY >= box.top &&
    event.clientY <= box.bottom
  )
}

function endLift() {
  lifted = null
  document.body.classList.remove('reordering')
}

provide(filterLiftKey, {
  handlers: (id: string) => ({
    pointerdown: (event: PointerEvent) => {
      // A chip's own controls own their presses, so a condition is not dragged by its remove.
      if (event.button !== 0 || (event.target as HTMLElement).closest('button') != null) {
        return
      }

      event.stopPropagation()
      lifted = {
        id,
        pointerId: event.pointerId,
        origin: event.clientX,
        x: event.clientX,
        moved: false,
      }
    },
    pointermove: (event: PointerEvent) => {
      if (lifted == null || event.pointerId !== lifted.pointerId) {
        return
      }

      lifted.x = event.clientX
      if (!lifted.moved && Math.abs(lifted.x - lifted.origin) < 4) {
        return
      }

      // Captured only once the press has become a drag, so a plain click still reaches the chip.
      if (!lifted.moved) {
        ;(event.currentTarget as HTMLElement).setPointerCapture(lifted.pointerId)
        document.body.classList.add('reordering')
      }

      lifted.moved = true
    },
    pointerup: (event: PointerEvent) => {
      if (lifted == null || event.pointerId !== lifted.pointerId) {
        return
      }

      const dropped = lifted
      endLift()

      if (!dropped.moved || isOverOwnBlock(dropped.id, event)) {
        return
      }

      query = withMovedToRoot(query, dropped.id, rootIndexAt(event.clientX))
    },
    pointercancel: endLift,
  }),
  styleFor: (id: string) =>
    lifted?.id === id && lifted.moved
      ? { transform: `translateX(${lifted.x - lifted.origin}px)`, zIndex: '1' }
      : undefined,
})
</script>

<template>
  <div
    ref="rootElement"
    class="flex min-h-6 flex-nowrap items-center gap-1 px-1.5 py-0.5"
    tabindex="-1"
    @keydown="onBarKeydown"
    @pointerdown.self="selection.clear()"
    @pointermove="onBarPointerMove"
  >
    <c-icon class="text-muted shrink-0" :name="icons.search" size="12" />
    <!-- Only the conditions scroll. An overflow on the bar itself would clip the suggestions,
    since an overflow on one axis makes the other scroll too. The scrollbar is hidden, a row of
    its own being most of the height of a control this size. -->
    <c-context-menu
      class="min-w-0 shrink overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      :items="contextMenuItems"
    >
      <div class="flex flex-nowrap items-center gap-1">
        <div
          v-for="(item, index) in query"
          :key="item.id"
          class="shrink-0"
          data-filter-chip
          :style="reorder.styleFor(index)"
          v-on="reorder.handlers(index)"
          @click="onChipClick(item.id, $event)"
          @contextmenu="selection.ensureSelected(item.id)"
        >
          <c-filter-item
            :address-options="addressOptions"
            :focus-id="focusId"
            :group-target="groupTargetId === item.id"
            :item="item"
            :selected="selection.isSelected(item.id)"
            @change="onChange"
            @commit="onCommit"
            @operator="onOperator"
            @remove="onRemove"
          />
        </div>
      </div>
    </c-context-menu>
    <!-- Set off from the last chip so the caret does not sit against it. -->
    <!-- Sized from nothing, so it holds only what the conditions leave over and never bids for the
    room they need. They reach the edge of the bar before any of them scrolls out of sight, and the
    floor keeps somewhere to type once they have filled it. -->
    <div class="relative min-w-8 flex-1 pl-1">
      <input
        ref="inputElement"
        v-model="search"
        class="w-full bg-transparent py-0.5 font-mono text-[11px] outline-none"
        placeholder=""
        spellcheck="false"
        type="text"
        @blur="isInputFocused = false"
        @focus="isInputFocused = true"
        @keydown.backspace="onInputBackspace()"
        @keydown.down.prevent="highlighted = Math.min(highlighted + 1, suggestionCount - 1)"
        @keydown.enter.prevent="onEnter()"
        @keydown.escape="search = ''"
        @keydown.tab="onTab"
        @keydown.up.prevent="highlighted = Math.max(highlighted - 1, 0)"
      />
      <!-- Offered while typing, mousedown so the pick lands before the input's blur. -->
      <div
        v-if="isSuggesting && search.trim() !== ''"
        :class="[
          'bg-elevated border-default absolute top-full left-0 z-10 mt-1',
          'max-h-64 min-w-44 overflow-y-auto rounded-md border py-1 shadow-lg',
        ]"
      >
        <button
          v-if="groupingOperator != null"
          class="flex w-full cursor-pointer items-baseline gap-0 px-2 py-0.5 text-left"
          :class="highlighted === 0 && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="acceptGrouping(groupingOperator)"
          @mousemove="highlighted = 0"
        >
          <c-text element="span" variant="mono-sm">Group</c-text>
          <c-text class="text-muted" element="span" variant="mono-xs"
            >: {{ groupingOperator }}</c-text
          >
        </button>
        <button
          v-if="freeTextDefinition != null"
          class="flex w-full cursor-pointer items-baseline gap-0 px-2 py-0.5 text-left"
          :class="freeTextIndex === highlighted && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="acceptFreeText()"
          @mousemove="highlighted = groupingCount + 0"
        >
          <c-text element="span" variant="mono-sm">{{ freeTextDefinition.label }}</c-text>
          <!-- The text as typed, shown as the value it would be given, since this row differs from
          the ones above by carrying one already. -->
          <c-text class="text-muted truncate" element="span" variant="mono-xs"
            >: str = "{{ search.trim() }}"</c-text
          >
        </button>
        <button
          v-for="(suggestion, index) in valueSuggestions"
          :key="`${suggestion.definition.kind}=${suggestion.value}`"
          class="flex w-full cursor-pointer items-baseline gap-0 px-2 py-0.5 text-left"
          :class="index + valuesOffset === highlighted && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="acceptValue(suggestion)"
          @mousemove="highlighted = index + valuesOffset"
        >
          <c-text element="span" variant="mono-sm">{{ suggestion.definition.label }}</c-text>
          <c-text class="text-muted truncate" element="span" variant="mono-xs"
            >: {{ typeLabel(suggestion.definition.input) }} = "{{ suggestion.value }}"</c-text
          >
          <!-- Says which row Tab lands on, that being the only way to reach it without leaving
          the keys the typing is already on. -->
          <div class="grow" />
          <c-icon
            v-if="index + valuesOffset === tabRow"
            class="text-muted ml-2 shrink-0 self-center"
            :name="icons.keyboardTab"
            size="13"
          />
        </button>
        <!-- Last, a field being an unfinished condition where everything above it is a whole
        one. -->
        <button
          v-for="(definition, index) in suggestions"
          :key="definition.kind"
          class="flex w-full cursor-pointer items-baseline gap-0 px-2 py-0.5 text-left"
          :class="index + fieldsOffset === highlighted && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="accept(definition)"
          @mousemove="highlighted = index + fieldsOffset"
        >
          <c-text element="span" variant="mono-sm">{{ definition.label }}</c-text>
          <c-text class="text-muted" element="span" variant="mono-xs"
            >: {{ typeLabel(definition.input) }}</c-text
          >
          <div class="grow" />
          <c-icon
            v-if="index + fieldsOffset === tabRow"
            class="text-muted ml-2 shrink-0 self-center"
            :name="icons.keyboardTab"
            size="13"
          />
        </button>
      </div>
    </div>
  </div>
</template>
