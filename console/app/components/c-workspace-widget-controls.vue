<script lang="ts" setup>
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import { ButtonActionModel } from '@/workspace'
import type { ControlsWidget } from '@/workspace'

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
  <!-- Wrapping lets the widget hold any number of buttons at any width, with the controls of
  every kind centered in the room the widget gives them. -->
  <div
    :class="
      widget.buttons.length > 0
        ? ['group flex flex-wrap items-center justify-center gap-1.5']
        : ['flex min-h-[34px] flex-col items-center justify-center']
    "
  >
    <template v-if="widget.buttons.length > 0">
      <div
        v-for="(button, at) in widget.buttons"
        :key="button.id"
        :ref="(item) => setItem(at, item as Element | null)"
        class="inline-flex touch-none transition-transform duration-[160ms] ease-[ease]"
        :class="[
          // A held button tracks the pointer directly, and the ones sliding aside move at once,
          // so neither smooths its own movement. The transition returns on release.
          reorder.isSwapping && 'transition-none',
          reorder.isHeld(at) && 'z-2',
          reorder.isGrabbed(at) && 'cursor-grabbing transition-none',
        ]"
        :style="reorder.styleFor(at)"
        v-on="reorder.handlers(at)"
        @click.capture="onItemClick"
      >
        <c-workspace-widget-control
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
      <div class="relative w-0 self-stretch">
        <c-tooltip text="Add Button">
          <!-- Offered only while the bar is being pointed at, so a finished bar reads as its
          buttons alone. -->
          <c-button
            :class="[
              'absolute top-1/2 left-0 -translate-y-1/2 opacity-0 transition-opacity duration-150',
              'group-hover:opacity-60 hover:opacity-100 focus:opacity-100',
            ]"
            :icon="icons.add"
            size="xs"
            variant="ghost"
            @click="addButton"
          />
        </c-tooltip>
      </div>
    </template>
    <!-- An empty bar offers only an add button, styled like an empty layout's centered round
    button so adding the first button works the same as adding a widget. -->
    <c-tooltip v-else text="Add Button">
      <c-button
        aria-label="Add Button"
        class="rounded-full"
        color="primary"
        :icon="icons.add"
        size="xs"
        @click="addButton"
      />
    </c-tooltip>
  </div>
</template>
