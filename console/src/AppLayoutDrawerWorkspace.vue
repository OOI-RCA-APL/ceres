<script lang="ts" setup>
import { useAuth } from '@/api/auth'
import icons from '@/icons'
import { Workspace } from '@/workspace'

const { workspace } = defineProps<{
  workspace: Workspace
}>()

const auth = useAuth()

// A private workspace only ever appears here for its own owner, so the lock is a reminder that
// nobody else can see it rather than a permission the viewer might lack.
const isPrivate = $computed(
  () => workspace.owner_id != null && workspace.owner_id === auth.user?.id
)
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
    <q-item-section v-if="isPrivate" side>
      <q-icon :class="$style.privateIcon" :name="icons.privateWorkspace" size="14px">
        <q-tooltip :delay="1000">This workspace is private to you.</q-tooltip>
      </q-icon>
    </q-item-section>
  </q-item>
</template>

<style module>
.privateIcon {
  margin-right: 5px;
}
</style>
