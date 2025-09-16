<script lang="ts" setup>
import icons from '@/icons'
import { useWorkspaces, Workspace } from '@/workspace'

const { workspace } = defineProps<{
  workspace: Workspace
}>()

const workspaces = useWorkspaces()
const membership = $computed(() => workspaces.getStoredMembership(workspace.id))
const icon = $computed(() => {
  if (membership == null) {
    return null
  }

  return icons[membership.role]
})
</script>

<template>
  <q-item clickable dense :to="`/workspaces/${workspace.id}`">
    <q-item-section avatar>
      <q-icon class="q-ml-md" :name="icons.circle" size="6px" />
    </q-item-section>
    <q-item-section>
      <q-item-label>
        <span class="q-ml-sm" style="text-wrap: nowrap">
          {{ workspace.name }}
        </span>
      </q-item-label>
    </q-item-section>
    <q-item-section v-if="membership != null" side>
      <q-icon v-if="icon != null" :class="$style.membershipIcon" :name="icon" size="14px">
        <q-tooltip :delay="1000">You are a {{ membership.role }} of this workspace.</q-tooltip>
      </q-icon>
    </q-item-section>
  </q-item>
</template>

<style module>
.membershipIcon {
  margin-right: 5px;
}
</style>
