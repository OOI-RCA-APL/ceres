<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'
import { inStandardOrder, Workspace } from '@/workspace'

const emit = defineEmits<{
  (emit: 'select', workspace: Workspace): void
  (emit: 'create'): void
}>()

const { items, scope, omit, empty } = defineProps<{
  /** Candidates to choose between. Without any, everything the caller can see is fetched. */
  items?: Workspace[] | null
  /** Placement to draw from, defaulting to everywhere. */
  scope?: string | null
  omit?: (workspace: Workspace) => boolean
  disable?: (workspace: Workspace) => boolean
  empty?: string | null
  /** Shown beneath the list, for a caller that offers making a new one from here. */
  createLabel?: string | null
}>()

const engine = useEngine()

let search = $ref('')

// Only fetched when the caller has not already said what to choose between, since a caller with a
// list in hand usually has one this component could not work out for itself.
const query = useQuery({
  queryKey: debouncedComputed(() => ['workspace-chooser', items == null], 100),
  queryFn: async () => (items != null ? [] : await engine.workspaces.getAll()),
  placeholderData: (previous) => previous,
})

const workspaces = $computed(() => {
  const text = search.trim().toLowerCase()
  let found = items ?? query.data.value ?? []

  if (scope != null) {
    found = found.filter((workspace) => workspace.scope.toString() === scope)
  }

  // Matched against the placement as well as the name, since a strip mixing placements is often
  // searched for what a workspace is bound to rather than for what it is called.
  if (text !== '') {
    found = found.filter(
      (workspace) =>
        workspace.name.toLowerCase().includes(text) ||
        workspace.scope.toString().toLowerCase().includes(text)
    )
  }

  if (omit != null) {
    found = found.filter((workspace) => !omit(workspace))
  }

  return inStandardOrder(found)
})

// A workspace on the engine root is not bound to anything, so there is no placement worth naming
// beside it.
function placementOf(workspace: Workspace): string | null {
  return workspace.scope.isEngine ? null : workspace.scope.toString()
}
</script>

<template>
  <div>
    <div class="q-pa-sm">
      <q-input
        v-model="search"
        autofocus
        class="q-mb-sm"
        dense
        label="Workspaces"
        outlined
        :spellcheck="false"
        @keyup.enter="
          () => {
            if (workspaces.length > 0) {
              emit('select', workspaces[0])
            }
          }
        "
      >
        <template #prepend>
          <q-icon :name="icons.search" />
        </template>
      </q-input>
      <div v-if="workspaces.length === 0" :class="[$style.emptyMessageText, 'q-pa-sm']">
        {{ empty ?? 'No workspaces found.' }}
      </div>
      <!-- The same bordered, separated rows the overview lists workspaces in, so a workspace looks
    like itself wherever it is being picked from. -->
      <q-list v-else bordered :class="[$style.list, 'rounded-borders', 'scroll']" dense separator>
        <q-item
          v-for="workspace in workspaces"
          :key="workspace.id"
          :active="workspaces.length === 1"
          clickable
          :disable="disable?.(workspace) ?? false"
          @click="$emit('select', workspace)"
        >
          <q-item-section avatar>
            <q-icon
              :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
              size="18px"
            >
              <q-tooltip v-if="workspace.owner_id != null" :delay="500">
                This workspace is private to you.
              </q-tooltip>
            </q-icon>
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ workspace.name }}</q-item-label>
            <q-item-label v-if="placementOf(workspace) != null" caption>
              {{ placementOf(workspace) }}
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </div>
    <!-- Offered under the list, so making a new one is reached from the same place as finding an
    existing one, and worn as a row so it sits with whatever else the caller offers beneath it
    rather than standing apart from them. -->
    <template v-if="createLabel != null">
      <q-separator />
      <q-list dense>
        <q-item clickable dense @click="$emit('create')">
          <q-item-section avatar>
            <q-icon :name="icons.add" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ createLabel }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </template>
  </div>
</template>

<style lang="scss" module>
.list {
  max-height: calc(40px * 3);
}

.emptyMessageText {
  text-align: center;
  font-size: 13px;
  opacity: 0.5;
}
</style>
