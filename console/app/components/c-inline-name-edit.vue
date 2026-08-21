<script lang="ts" setup>
import { onClickOutside } from '@vueuse/core'
import { nextTick, watch } from 'vue'

const {
  name,
  editing,
  claim = true,
} = defineProps<{
  name: string
  editing: boolean

  /** Whether opening should take focus as well as show the field.

  A field opened deliberately, from a menu or a shortcut, is meant to be typed into at once. One
  offered on hover is only an invitation, so it waits to be clicked into rather than stealing the
  caret from wherever it already was.
  */
  claim?: boolean
}>()

const emit = defineEmits<{
  'update:editing': [value: boolean]
  rename: [name: string]
  /** Backed out of without naming, which a caller that created something to be named can undo. */
  cancel: []
}>()

let draft = $ref(name)
let input = $ref<HTMLInputElement | null>(null)
let field = $ref<HTMLElement | null>(null)

// A press outside commits on its own rather than through blur, since a closing menu can move
// focus off the field and leave it with no blur to end the edit.
onClickOutside($$(field), commit)

// When the caret was claimed. Renaming is usually reached from a menu, and a menu hands focus back
// to whatever opened it as it closes, which lands just after the field has taken focus. That blur
// is the menu letting go rather than the user leaving, so for a moment after claiming the field
// takes focus back instead of treating it as being done with.
let openedAt = 0
const settleWindow = 400

// The name just submitted, shown in place of the stored one until the rename lands. Without it the
// old name comes back for as long as the write takes, which reads as the edit having been lost.
let pending = $ref<string | null>(null)

const shown = $computed(() => pending ?? name)

watch(
  () => name,
  () => {
    pending = null
  },
)

watch(
  () => ({ editing, claim }),
  async (now, before) => {
    if (!now.editing) {
      return
    }

    // The draft is seeded as editing begins rather than followed continuously, so a rename
    // landing from elsewhere while the field is open does not pull the text out from under the
    // cursor.
    if (before?.editing !== true) {
      draft = name
    }

    // A field offered on hover is already showing when a menu turns it into a real edit, so the
    // claim is what decides when to take the caret rather than the field appearing.
    if (!now.claim || before?.claim === true) {
      return
    }

    openedAt = performance.now()
    await nextTick()
    claimCaret()
  },
)

// A menu closing restores focus to whatever opened it, which lands after the field has already
// taken the caret, so the claim is retried until it holds or the settle window passes.
function claimCaret() {
  const attempt = () => {
    if (!editing || !claim || input == null || document.activeElement === input) {
      return
    }

    take()
    if (performance.now() - openedAt < settleWindow) {
      requestAnimationFrame(attempt)
    }
  }

  attempt()
}

// Focus lands with the caret after the name rather than over it, so typing continues the name
// instead of replacing it.
function take() {
  input?.focus()
  input?.setSelectionRange(draft.length, draft.length)
}

/** Which character a press at this position landed on.

Worked out from the text rather than asked of the browser, because refusing the press is what stops
shift dragging a selection out, and a refused press is one the browser never places a caret for.
The widths come from the field's own font, so the answer matches what is on screen.
*/
function caretAt(clientX: number): number {
  if (input == null) {
    return draft.length
  }

  const context = measurer()
  const style = getComputedStyle(input)
  if (context == null) {
    return draft.length
  }

  context.font = style.font || `${style.fontSize} ${style.fontFamily}`

  // Measured from where the text starts rather than from the edge of the field, and following it
  // if the name is long enough to have scrolled within.
  const box = input.getBoundingClientRect()
  const inset = parseFloat(style.paddingLeft || '0') + parseFloat(style.borderLeftWidth || '0')
  const target = clientX - box.left - inset + input.scrollLeft

  let closest = 0
  let smallest = Infinity
  for (let index = 0; index <= draft.length; index++) {
    const distance = Math.abs(context.measureText(draft.slice(0, index)).width - target)
    if (distance < smallest) {
      smallest = distance
      closest = index
    }
  }

  return closest
}

let measuringContext: CanvasRenderingContext2D | null = null

function measurer(): CanvasRenderingContext2D | null {
  measuringContext ??= document.createElement('canvas').getContext('2d')
  return measuringContext
}

// A field only being offered sits inside something that wants the press for itself, and a tab in
// particular takes focus back the moment it is clicked. Taking focus here rather than leaving it to
// the browser's own handling settles that, and the press is left to run so the caret still lands
// where it was aimed.
//
// Pressed into is also what turns an offer into a real edit, said here rather than waiting on a
// focus event, since focusing something already focused raises none and the edit would never be
// taken up.
function claimFocus(event: MouseEvent) {
  emit('update:editing', true)

  if (input == null) {
    return
  }

  // Already a real edit, so the field is its own and every press means what it would in any text
  // field, shift included. Only the press that takes an offer up needs handling.
  if (claim) {
    return
  }

  // Shift is still down on that first press, since holding it is what put the field here, and
  // shift with a press is how a text field is told to drag a selection out. Refusing it and
  // placing the caret leaves the field ready to type in rather than with its name selected.
  if (event.shiftKey) {
    event.preventDefault()

    const offset = caretAt(event.clientX)
    input.focus()
    input.setSelectionRange(offset, offset)
    return
  }

  input.focus()
}

function onBlur() {
  // Only a field that took focus for itself has a menu to outlast. One waiting to be clicked into
  // has nothing to hold on to, and leaving it is simply leaving.
  if (claim && editing && performance.now() - openedAt < settleWindow) {
    requestAnimationFrame(claimCaret)
    return
  }

  commit()
}

function commit() {
  if (!editing) {
    return
  }

  emit('update:editing', false)

  const trimmed = draft.trim()
  if (trimmed !== '' && trimmed !== name) {
    pending = trimmed
    emit('rename', trimmed)
  }
}

function cancel() {
  draft = name
  emit('update:editing', false)
  emit('cancel')
}
</script>

<template>
  <!-- The field is sized by a mirror of its own text, so it grows with what is typed and sits
  exactly where the name sat. Nothing around it moves as editing starts. -->
  <!-- The presses are taken on the whole field rather than on the input alone, since the field is
  a little wider than the text and a press landing on that margin would otherwise carry on to
  whatever the field is sitting in and be taken as opening it. -->
  <span
    v-if="editing"
    ref="field"
    :class="$style.field"
    :data-value="draft"
    @click.stop
    @dblclick.stop
    @mousedown.stop="claimFocus"
    @pointerdown.stop="claimFocus"
  >
    <!-- Sized down to a single character so the mirror behind it, not the field's own default
    width of twenty characters, decides how wide the cell is. Keys stay in the field as well, since
    a tab strip steers between its tabs with the arrow keys and would take the caret with it. -->
    <input
      ref="input"
      v-model="draft"
      :class="$style.input"
      size="1"
      spellcheck="false"
      type="text"
      @blur="onBlur"
      @focus="emit('update:editing', true)"
      @keydown.enter.prevent="commit"
      @keydown.esc.prevent="cancel"
      @keydown.stop
    />
  </span>
  <template v-else>{{ shown }}</template>
</template>

<style module>
/* The mirror and the field share one grid cell, so the cell is as wide as the text and the field
fills it. Sizing this in CSS keeps the width exact without measuring anything. The mirror holds
the text alone, so the cell is the width of the name and no wider, with the padding and the
filled backing carried out here where they do not stretch it. */
.field {
  display: inline-grid;
  /* The backing reaches out around the text rather than pushing it in, so the name sits in exactly
  the same place being edited as it does being read. The padding and the margin cancel. */
  margin: 0 -4px;
  padding: 0 4px;
  border-radius: 4px 4px 0 0;
  /* Drawn inside the box rather than as a border, so the underline adds no height and cannot push
  the text off the line it was sitting on. The box rides the surrounding baseline for the same
  reason, since aligning it any other way lifts the name as editing starts. */
  box-shadow: inset 0 -1px 0 currentColor;
  vertical-align: baseline;
  background: #0000000d;
}

.field::after {
  content: attr(data-value);
  visibility: hidden;
  white-space: pre;
  grid-area: 1 / 1;
}

:global(.dark) .field {
  background: #ffffff12;
}

/* Inherits everything it can from where it sits, so the name reads the same being edited as it
does being read, with the filled backing and the underline saying it is a field. */
.input {
  grid-area: 1 / 1;
  width: 100%;
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  outline: none;
}
</style>
