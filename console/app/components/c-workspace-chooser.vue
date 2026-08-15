<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'
import { inStandardOrder, type Workspace } from '@/workspace'

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

function submitFirst() {
  const first = workspaces[0]
  if (first != null) {
    emit('select', first)
  }
}
</script>

<template>
  <div>
    <div class="p-2">
      <c-input
        v-model="search"
        autofocus
        class="mb-2 w-full"
        :icon="icons.search"
        placeholder="Workspaces"
        size="sm"
        :spellcheck="false"
        @keyup.enter="submitFirst"
      />
      <c-text
        v-if="workspaces.length === 0"
        class="block p-2 text-center opacity-50"
        variant="body2"
      >
        {{ empty ?? 'No workspaces found.' }}
      </c-text>
      <!-- The same bordered, separated rows the overview lists workspaces in, so a workspace looks
      like itself wherever it is being picked from. -->
      <div
        v-else
        class="max-h-[120px] divide-y divide-default overflow-y-auto rounded-md border border-default"
      >
        <button
          v-for="workspace in workspaces"
          :key="workspace.id"
          class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-elevated disabled:opacity-50"
          :class="workspaces.length === 1 && 'bg-elevated'"
          :disabled="disable?.(workspace) ?? false"
          type="button"
          @click="$emit('select', workspace)"
        >
          <c-tooltip
            :delay-duration="500"
            :disabled="workspace.owner_id == null"
            text="This workspace is private to you."
          >
            <c-icon
              class="shrink-0"
              :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
              size="18"
            />
          </c-tooltip>
          <span class="min-w-0">
            <c-text class="block truncate" variant="body2">{{ workspace.name }}</c-text>
            <c-text
              v-if="placementOf(workspace) != null"
              class="block truncate"
              variant="description"
            >
              {{ placementOf(workspace) }}
            </c-text>
          </span>
        </button>
      </div>
    </div>
    <!-- Offered under the list, so making a new one is reached from the same place as finding an
    existing one, and worn as a row so it sits with whatever else the caller offers beneath it
    rather than standing apart from them. -->
    <template v-if="createLabel != null">
      <c-separator />
      <button
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-elevated"
        type="button"
        @click="$emit('create')"
      >
        <c-icon class="shrink-0" :name="icons.add" size="18" />
        <c-text variant="body2">{{ createLabel }}</c-text>
      </button>
    </template>
  </div>
</template>
