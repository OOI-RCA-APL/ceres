<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { nextTick } from 'vue'

import {
  defaultTextKind,
  definitionsFor,
  getFilterDefinition,
  matchDefinitions,
} from '@/filters/definitions'
import type { FilterDefinition, RecordKind } from '@/filters/definitions'
import {
  createBlock,
  createCondition,
  isBlock,
  withAppendedTo,
  withBlockOp,
  withConditionValue,
  withoutItems,
} from '@/filters/model'
import type { FilterItem, FilterQuery } from '@/filters/model'
import { createFilterSelection } from '@/filters/selection'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import type { SelectMode } from '@/workspace'

const { recordKind, addressOptions = [] } = defineProps<{
  recordKind: RecordKind
  /** The choices an address condition offers, from the hosting view's scope. */
  addressOptions?: readonly string[]
}>()

let query = $(defineModel<FilterQuery>({ required: true }))

const selection = createFilterSelection({
  query: () => query,
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

/** Where the free text entry sits, which is after every field it is offered beneath. */
const groupingCount = $computed(() => (groupingOperator == null ? 0 : 1))
const freeTextIndex = $computed(() =>
  freeTextDefinition == null ? -1 : groupingCount + suggestions.length,
)
const suggestionCount = $computed(
  () => groupingCount + suggestions.length + (freeTextDefinition == null ? 0 : 1),
)
const isSuggesting = $computed(() => isInputFocused && suggestionCount > 0)

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

  const definition = suggestions[highlighted - groupingCount] ?? suggestions[0]
  if (definition != null) {
    accept(definition)
  } else {
    acceptFreeText()
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
}

function onBarKeydown(event: KeyboardEvent) {
  // Value inputs and the bar's own input handle their own keys.
  if (event.target instanceof HTMLInputElement) {
    return
  }

  if (event.key === 'Delete' || event.key === 'Backspace') {
    selection.removeSelected()
    event.preventDefault()
  } else if ((event.metaKey || event.ctrlKey) && event.key === 'c') {
    selection.copySelected()
  } else if ((event.metaKey || event.ctrlKey) && event.key === 'x') {
    selection.cutSelected()
  } else if ((event.metaKey || event.ctrlKey) && event.key === 'v') {
    selection.paste()
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

/** Append a condition of `kind` and focus its value input, the header quick filters' path
into the bar. */
function appendKind(kind: string) {
  const condition = createCondition(kind, null)
  append(condition)
  focusId = condition.id
}

defineExpose({ appendKind })

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => [...(rootElement?.querySelectorAll<HTMLElement>('[data-filter-chip]') ?? [])],
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
</script>

<template>
  <div
    ref="rootElement"
    class="flex min-h-6 flex-wrap items-center gap-1 px-1.5 py-0.5"
    tabindex="-1"
    @keydown="onBarKeydown"
    @pointerdown.self="selection.clear()"
  >
    <c-icon class="text-muted shrink-0" :name="icons.search" size="12" />
    <c-context-menu :items="contextMenuItems">
      <div class="flex flex-wrap items-center gap-1">
        <div
          v-for="(item, index) in query"
          :key="item.id"
          data-filter-chip
          :style="reorder.styleFor(index)"
          v-on="reorder.handlers(index)"
          @click="onChipClick(item.id, $event)"
          @contextmenu="selection.ensureSelected(item.id)"
        >
          <c-filter-item
            :address-options="addressOptions"
            :focus-id="focusId"
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
    <div class="relative min-w-24 grow pl-1">
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
          class="flex w-full cursor-pointer items-baseline gap-2 px-2 py-0.5 text-left"
          :class="highlighted === 0 && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="acceptGrouping(groupingOperator)"
          @mousemove="highlighted = 0"
        >
          <c-text element="span" variant="mono-sm">Group</c-text>
          <c-text class="text-muted" element="span" variant="mono-xs">
            : {{ groupingOperator }}
          </c-text>
        </button>
        <button
          v-for="(definition, index) in suggestions"
          :key="definition.kind"
          class="flex w-full cursor-pointer items-baseline gap-2 px-2 py-0.5 text-left"
          :class="index + groupingCount === highlighted && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="accept(definition)"
          @mousemove="highlighted = index + groupingCount"
        >
          <c-text element="span" variant="mono-sm">{{ definition.label }}</c-text>
          <c-text class="text-muted" element="span" variant="mono-xs">
            : {{ definition.input.type }}
          </c-text>
        </button>
        <button
          v-if="freeTextDefinition != null"
          class="flex w-full cursor-pointer items-baseline gap-2 px-2 py-0.5 text-left"
          :class="freeTextIndex === highlighted && 'bg-accented/60'"
          type="button"
          @mousedown.prevent="acceptFreeText()"
          @mousemove="highlighted = suggestionCount - 1"
        >
          <c-text element="span" variant="mono-sm">{{ freeTextDefinition.label }}</c-text>
          <!-- The text as typed, shown as the value it would be given, since this row differs from
          the ones above by carrying one already. -->
          <c-text class="text-muted truncate" element="span" variant="mono-xs">
            : str = "{{ search.trim() }}"
          </c-text>
        </button>
      </div>
    </div>
  </div>
</template>
