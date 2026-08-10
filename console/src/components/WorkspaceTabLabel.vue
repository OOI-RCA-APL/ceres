<script lang="ts" setup>
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import icons from '@/icons'
import { Workspace } from '@/workspace'

const {
  workspace,
  showPlacement,
  editing = false,
  claim = true,
} = defineProps<{
  workspace: Workspace
  /** Whether this strip mixes placements, in which case every tab names its own. */
  showPlacement: boolean
  /** Whether the name is being edited in place. */
  editing?: boolean
  /** Whether showing the field should take focus, or leave it to be clicked into. */
  claim?: boolean
}>()

defineEmits<{
  'update:editing': [value: boolean]
  rename: [name: string]
  /** Whether the pointer is over the name itself, which offers a rename. */
  hoverName: [value: boolean]
}>()

const isPrivate = $computed(() => workspace.owner_id != null)

// A component page's tabs all share one placement so naming it on every tab would be noise. Home
// can hold workspaces from anywhere, and there the placement is what tells two tabs apart.
const placement = $computed(() =>
  showPlacement && !workspace.scope.isEngine ? workspace.scope.toString() : null
)
</script>

<template>
  <!-- One root rather than a row of siblings so a class or a listener put on this component by
  whoever is using it lands somewhere. Vue has nowhere to put either on a component that renders
  several roots, and drops them without a word. -->
  <span :class="[$style.root, 'items-center', 'no-wrap', 'row']">
    <q-icon :class="$style.icon" :name="isPrivate ? icons.privateWorkspace : icons.workspace">
      <q-tooltip v-if="isPrivate" :delay="1000">This workspace is private to you.</q-tooltip>
    </q-icon>
    <span v-if="placement != null" :class="$style.placement">{{ placement }}&nbsp;/&nbsp;</span>
    <!-- The name alone reports being hovered. Holding shift over a tab offers to rename it, and
    the offer belongs to the text being renamed rather than to the whole tab. -->
    <span
      :class="[$style.name, editing && $style.editingName]"
      @mouseenter="$emit('hoverName', true)"
      @mouseleave="$emit('hoverName', false)"
    >
      <inline-name-edit
        :claim
        :editing
        :name="workspace.name"
        @rename="(value: string) => $emit('rename', value)"
        @update:editing="(value: boolean) => $emit('update:editing', value)"
      />
    </span>
    <q-tooltip v-if="placement != null && !editing" :delay="1000">
      {{ placement }} / {{ workspace.name }}
    </q-tooltip>
  </span>
</template>

<style lang="scss" module>
// Shrinks with the tab so the name inside it can still truncate.
.root {
  min-width: 0;
}

.icon {
  font-size: 15px;
  margin-right: 5px;
}

// The address is what tells two same-named tabs apart so it keeps its full width while the name
// truncates. It is dimmed so the eye lands on what the tab is with the context still available.
.placement {
  flex: none;
  font-size: 13px;
  opacity: 0.65;
  white-space: nowrap;
}

.name {
  max-width: 160px;
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// A name being edited is not truncated since the ellipsis that keeps a tab narrow would clip the
// text being typed and the caret with it. The field grows with what is typed and the tab with it.
.editingName {
  max-width: none;
  overflow: visible;
}
</style>
