<script lang="ts" setup>
import icons from '@/icons'
import type { Workspace } from '@/workspace'

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
  showPlacement && !workspace.scope.isEngine ? workspace.scope.toString() : null,
)
</script>

<!-- One root rather than a row of siblings so a class or a listener put on this component by
whoever is using it lands somewhere. -->
<template>
  <c-tooltip
    :delay-duration="1000"
    :disabled="placement == null || editing"
    :text="`${placement} / ${workspace.name}`"
  >
    <span class="flex min-w-0 flex-nowrap items-center">
      <!-- Only a private workspace is marked, its icon saying who can see it. A shared one needs no
      mark, a strip of tabs inviting reordering on its own. -->
      <c-tooltip v-if="isPrivate" :delay-duration="1000" text="This workspace is private to you.">
        <c-icon class="mr-[5px] shrink-0 text-[15px]" :name="icons.privateWorkspace" />
      </c-tooltip>
      <!-- The address is what tells two same-named tabs apart so it keeps its full width while the
      name truncates. It is dimmed so the eye lands on what the tab is with the context still
      available. -->
      <span v-if="placement != null" class="flex-none whitespace-nowrap text-[13px] opacity-65">
        {{ placement }}&nbsp;/&nbsp;
      </span>
      <!-- The name alone reports being hovered. Holding shift over a tab offers to rename it, and
      the offer belongs to the text being renamed rather than to the whole tab. -->
      <!-- A name being edited is not truncated since the ellipsis that keeps a tab narrow would
      clip the text being typed and the caret with it. -->
      <span
        class="text-[13px]"
        :class="
          editing
            ? 'max-w-none overflow-visible'
            : 'max-w-40 overflow-hidden text-ellipsis whitespace-nowrap'
        "
        @mouseenter="$emit('hoverName', true)"
        @mouseleave="$emit('hoverName', false)"
      >
        <c-inline-name-edit
          :claim
          :editing
          :name="workspace.name"
          @rename="(value: string) => $emit('rename', value)"
          @update:editing="(value: boolean) => $emit('update:editing', value)"
        />
      </span>
    </span>
  </c-tooltip>
</template>
