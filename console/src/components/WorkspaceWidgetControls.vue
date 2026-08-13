<script lang="ts" setup>
import WorkspaceWidgetControl from '@/components/WorkspaceWidgetControl.vue'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import { ButtonActionModel, ControlsWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ControlsWidget
}>()

// The draggable elements are the buttons themselves rather than the wrappers so a press on a
// button's own dots does not drag it. Keyed by index because an array ref does not guarantee
// source order.
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

// A press that turned into a drag has already done what it was for so the click it releases
// into must not also press the button.
function onItemClick(event: MouseEvent) {
  if (reorder.consumeClick()) {
    event.preventDefault()
    event.stopPropagation()
  }
}

function addButton() {
  widget.buttons = [...widget.buttons, ButtonActionModel.parse({})]
}

/** Insert a fresh button at `at`, for the menu's before and after entries. */
function addButtonAt(at: number) {
  const buttons = [...widget.buttons]
  buttons.splice(at, 0, ButtonActionModel.parse({}))
  widget.buttons = buttons
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
          @add-after="addButtonAt(at + 1)"
          @add-before="addButtonAt(at)"
          @duplicate="duplicateButton(at)"
          @remove="removeButton(at)"
        />
      </div>
      <!-- The anchor spends no room in the row, so the button hangs past the last control
      rather than wrapping alone or skewing the centering, and clips at the widget's edge
      when there is no room left. -->
      <div :class="$style.addAnchor">
        <q-btn :class="$style.add" dense flat :icon="icons.add" round size="sm" @click="addButton">
          <q-tooltip class="bg-primary text-white">Add Button</q-tooltip>
        </q-btn>
      </div>
    </template>
    <!-- An empty bar offers only an add button, styled like an empty layout's centered round
    button so adding the first button works the same as adding a widget. -->
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
/* Wraps so the widget holds any number of buttons at any width, with the controls of every
kind centered in the room the widget gives them. */
.bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
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

/* The held button tracks the pointer directly so it must not smooth its own movement. The
transition returns on release and animates it into the gap. */
.grabbed {
  cursor: grabbing;
  transition: none;
}

/* The buttons sliding aside move at once rather than each animating from wherever they were. */
.swapping {
  transition: none;
}

.addAnchor {
  position: relative;
  align-self: stretch;
  width: 0;
}

/* Offered only while the bar is being pointed at so a finished bar reads as its buttons alone. */
.add {
  position: absolute;
  top: 50%;
  left: 0;
  transform: translateY(-50%);
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
