<script lang="ts" setup>
import icons from '@/icons'
import { Workspace } from '@/workspace'

const { workspace, showPlacement } = defineProps<{
  workspace: Workspace
  /** Whether this strip mixes placements, in which case every tab names its own. */
  showPlacement: boolean
}>()

const isPrivate = $computed(() => workspace.owner_id != null)

// A component page's tabs all share one placement, so naming it on every tab would be noise. Home
// can hold workspaces from anywhere, and there the placement is what tells two tabs apart.
const placement = $computed(() =>
  showPlacement && !workspace.scope.isEngine ? workspace.scope.toString() : null
)
</script>

<template>
  <q-icon :class="$style.icon" :name="isPrivate ? icons.privateWorkspace : icons.workspace">
    <q-tooltip v-if="isPrivate" :delay="1000">This workspace is private to you.</q-tooltip>
  </q-icon>
  <span v-if="placement != null" :class="$style.placement">{{ placement }}&nbsp;/&nbsp;</span>
  <span :class="$style.name">{{ workspace.name }}</span>
  <q-tooltip v-if="placement != null" :delay="1000">
    {{ placement }} / {{ workspace.name }}
  </q-tooltip>
</template>

<style lang="scss" module>
.icon {
  font-size: 15px;
  margin-right: 5px;
}

// The address is what tells two same-named tabs apart, so it keeps its full width while the name
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
</style>
