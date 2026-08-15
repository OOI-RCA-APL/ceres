<script lang="ts" setup>
import type { CommandPaletteItem } from '@nuxt/ui'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'
import { inStandardOrder, type Workspace } from '@/workspace'

const emit = defineEmits<{
  (emit: 'select', workspace: Workspace): void
  (emit: 'create'): void
}>()

const { items, scope, omit, disable, empty } = defineProps<{
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
        workspace.scope.toString().toLowerCase().includes(text),
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

// Matched above against both the name and the placement, so the palette shows what it was given
// rather than narrowing it again on the name alone.
const groups = $computed(() => [
  {
    id: 'workspaces',
    ignoreFilter: true,
    items: workspaces.map((workspace) => ({
      label: workspace.name,
      description: placementOf(workspace) ?? undefined,
      disabled: disable?.(workspace) ?? false,
      workspace,
    })),
  },
])

function onSelect(item: CommandPaletteItem & { workspace?: Workspace }) {
  if (item.workspace != null) {
    emit('select', item.workspace)
  }
}
</script>

<template>
  <div>
    <c-command-palette
      v-model:search-term="search"
      class="max-h-[210px]"
      :groups
      placeholder="Workspaces"
      @update:model-value="onSelect"
    >
      <template #item-leading="{ item }">
        <c-tooltip
          :delay-duration="500"
          :disabled="item.workspace.owner_id == null"
          text="This workspace is private to you."
        >
          <c-icon
            class="shrink-0"
            :name="item.workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
            size="18"
          />
        </c-tooltip>
      </template>
      <template #empty>
        <c-text class="block p-2 text-center opacity-50" variant="body2">
          {{ empty ?? 'No workspaces found.' }}
        </c-text>
      </template>
    </c-command-palette>
    <!-- Offered under the list, so making a new one is reached from the same place as finding an
    existing one, and worn as a row so it sits with whatever else the caller offers beneath it
    rather than standing apart from them. -->
    <template v-if="createLabel != null">
      <c-separator />
      <c-list-item @click="$emit('create')">
        <c-icon class="shrink-0" :name="icons.add" size="18" />
        <c-text variant="body2">{{ createLabel }}</c-text>
      </c-list-item>
    </template>
  </div>
</template>
