<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import WorkspaceWidgetButtonAction from '@/components/WorkspaceWidgetButtonAction.vue'
import icons from '@/icons'
import { moved } from '@/reorder'
import { ButtonActionModel, ButtonWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ButtonWidget
}>()

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

function moveButton(at: number, by: number) {
  const to = at + by
  if (to < 0 || to >= widget.buttons.length) {
    return
  }

  widget.buttons = moved([...widget.buttons], at, to)
}
</script>

<template>
  <div :class="[$style.bar, 'items-center']">
    <workspace-widget-button-action
      v-for="(button, at) in widget.buttons"
      :key="button.id"
      :button
      :first="at === 0"
      :last="at === widget.buttons.length - 1"
      @duplicate="duplicateButton(at)"
      @move="(by: number) => moveButton(at, by)"
      @remove="removeButton(at)"
    />
    <q-btn
      v-if="widget.buttons.length > 0"
      class="faded-hover"
      :class="$style.add"
      dense
      flat
      :icon="icons.add"
      round
      size="sm"
      @click="addButton"
    >
      <q-tooltip class="bg-primary text-white">Add Button</q-tooltip>
    </q-btn>
    <div v-else :class="[$style.empty, 'items-center', 'row']">
      <common-text variant="description">No buttons yet.</common-text>
      <q-btn
        class="q-ml-sm"
        color="primary"
        dense
        flat
        :icon="icons.add"
        label="Add Button"
        no-caps
        size="sm"
        @click="addButton"
      />
    </div>
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

.empty {
  opacity: 0.7;
}

.add {
  opacity: 0.5;
}

.bar:hover .add {
  opacity: 1;
}
</style>
