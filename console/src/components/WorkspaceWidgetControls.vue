<script lang="ts" setup>
import WorkspaceWidgetControl from '@/components/WorkspaceWidgetControl.vue'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import { ButtonActionModel, ControlsWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ControlsWidget
}>()

// Buttons drag along the bar the way tabs and carousel dots do, since it is the same gesture on
// the same kind of row. The elements handed over are the buttons themselves rather than the
// wrappers, so a press on the button drags it while a press on its own dots does not. Collected
// under their own indices, because an array ref makes no promise about matching the source order.
const items = new Map<number, HTMLElement>()

function setItem(at: number, item: Element | null) {
  if (item == null) {
    items.delete(at)
  } else {
    items.set(at, item as HTMLElement)
  }
}

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () =>
    widget.buttons
      .map((_, at) => items.get(at)?.querySelector('button'))
      .filter((element): element is HTMLButtonElement => element != null),
  onReorder: (from, to) => {
    widget.buttons = moved([...widget.buttons], from, to)
  },
})

// A press that turned into a drag has already done what it was for, so the click it releases
// into must not also press the button.
function onItemClick(event: MouseEvent) {
  if (reorder.consumeClick()) {
    event.preventDefault()
    event.stopPropagation()
  }
}

// Buttons are added, arranged and taken away on the bar itself, in the place they will be pressed,
// rather than described in a dialog somewhere away from it.
function addButton() {
  widget.buttons = [...widget.buttons, ButtonActionModel.parse({})]
}

function removeButton(at: number) {
  widget.buttons = widget.buttons.filter((_, position) => position !== at)
}

function duplicateButton(at: number) {
  const source = widget.buttons[at]
  if (source == null) {
    return
  }

  const buttons = [...widget.buttons]
  buttons.splice(at + 1, 0, ButtonActionModel.parse({ ...source, id: undefined }))
  widget.buttons = buttons
}
</script>

<template>
  <div
    :class="
      widget.buttons.length > 0
        ? [$style.bar, 'items-center']
        : [$style.empty, 'column', 'flex-center']
    "
  >
    <template v-if="widget.buttons.length > 0">
      <div
        v-for="(button, at) in widget.buttons"
        :key="button.id"
        :ref="(item) => setItem(at, item as Element | null)"
        :class="[
          $style.item,
          reorder.isSwapping && $style.swapping,
          reorder.isHeld(at) && $style.held,
          reorder.isGrabbed(at) && $style.grabbed,
        ]"
        :style="reorder.styleFor(at)"
        v-bind="reorder.handlers(at)"
        @click.capture="onItemClick"
      >
        <workspace-widget-control
          :button
          @duplicate="duplicateButton(at)"
          @remove="removeButton(at)"
        />
      </div>
      <q-btn :class="$style.add" dense flat :icon="icons.add" round size="sm" @click="addButton">
        <q-tooltip class="bg-primary text-white">Add Button</q-tooltip>
      </q-btn>
    </template>
    <!-- An empty bar offers the one thing there is to do with it, wearing the same centered
    round button an empty layout does, so the first button arrives the way a widget does. -->
    <q-btn
      v-else
      aria-label="Add Button"
      color="primary"
      :icon="icons.add"
      round
      size="8px"
      unelevated
      @click="addButton"
    >
      <q-tooltip class="bg-primary">Add Button</q-tooltip>
    </q-btn>
  </div>
</template>

<style module>
/* Buttons run along the bar and wrap onto another line once they outgrow it, so a widget holds as
many as are put on it whatever width it happens to have. */
.bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* Tall enough to center in when the widget stands at its minimum height without a frame. */
.empty {
  min-height: 34px;
}

.item {
  display: inline-flex;
  touch-action: none;
  transition: transform 160ms ease;
}

.held {
  z-index: 2;
}

/* The held button tracks the pointer directly, so it must not smooth its own movement. It regains
the transition once released, which is what animates it into the gap. */
.grabbed {
  cursor: grabbing;
  transition: none;
}

/* The buttons sliding aside move at once rather than each animating from wherever they were. */
.swapping {
  transition: none;
}

/* Offered only while the bar is being pointed at, so a finished bar reads as its buttons alone. */
.add {
  opacity: 0;
  transition: opacity 0.15s;
}

.bar:hover .add,
.add:focus {
  opacity: 0.6;
}

.bar .add:hover,
.add:focus {
  opacity: 1;
}
</style>
