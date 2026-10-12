<script lang="ts" setup>
import type { CommandPaletteItem } from '@nuxt/ui'
import { watchEffect } from 'vue'

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

type Kind = 'global' | 'associated'

// Global and associated workspaces sit under tabs of their own, since a name alone rarely says
// which kind it is. A chooser held to one placement has only one kind, so it shows no tabs.
let kind = $ref<Kind>('global')
let kindChosen = false

// Only fetched when the caller has not already said what to choose between, since a caller with a
// list in hand usually has one this component could not work out for itself.
const query = useQuery({
  queryKey: debouncedComputed(() => ['workspace-chooser', items == null], 100),
  queryFn: async () => (items != null ? [] : await engine.workspaces.getAll()),
  placeholderData: (previous) => previous,
})

const available = $computed(() => {
  let found = items ?? query.data.value ?? []
  if (scope != null) {
    found = found.filter((workspace) => workspace.scope.toString() === scope)
  }
  if (omit != null) {
    found = found.filter((workspace) => !omit(workspace))
  }

  return found
})

const counts = $computed(() => {
  const global = available.filter((workspace) => workspace.scope.isEngine).length
  return { global, associated: available.length - global }
})

const tabbed = $computed(() => scope == null)

const tabs = $computed(() => [
  { label: 'Global', value: 'global', count: counts.global },
  { label: 'Associated', value: 'associated', count: counts.associated },
])

// Opens on whichever kind has anything to offer, Global first, until a tab is picked by hand.
watchEffect(() => {
  if (!kindChosen) {
    kind = counts.global > 0 || counts.associated === 0 ? 'global' : 'associated'
  }
})

function chooseKind(value: string | number) {
  kindChosen = true
  kind = value as Kind
}

const workspaces = $computed(() => {
  const text = search.trim().toLowerCase()
  let found = available

  if (tabbed) {
    found = found.filter((workspace) => workspace.scope.isEngine === (kind === 'global'))
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

  return inStandardOrder(found)
})

// A workspace on the engine root is not bound to anything, so there is no placement worth naming
// beside it.
function placementOf(workspace: Workspace): string | null {
  return workspace.scope.isEngine ? null : workspace.scope.toString()
}

function itemOf(workspace: Workspace, described: boolean, indent = '') {
  return {
    label: workspace.name,
    description: described ? (placementOf(workspace) ?? undefined) : undefined,
    disabled: disable?.(workspace) ?? false,
    class: indent,
    workspace,
  }
}

/** A component heading in the tree, with how deep it sits. */
type Heading = { address: string; depth: number }

// Static so Tailwind sees each one, deeper nesting sharing the last.
const indents = ['pl-2', 'pl-6', 'pl-10', 'pl-14', 'pl-18']

function ancestorsOf(address: string): string[] {
  const parts = address.split('.')
  return parts.slice(1).map((_, index) => parts.slice(0, index + 1).join('.'))
}

// Associated workspaces sit under their component, nested by address. A group with no rows of its
// own is never drawn, so an ancestor without workspaces heads the first group beneath it instead.
const tree = $computed(() => {
  const byPlacement = new Map<string, Workspace[]>()
  for (const workspace of workspaces) {
    const address = workspace.scope.toString()
    byPlacement.set(address, [...(byPlacement.get(address) ?? []), workspace])
  }

  const drawn = new Set<string>()
  return [...byPlacement.keys()].sort().map((address) => {
    const headings: Heading[] = [...ancestorsOf(address), address]
      .filter((each) => !drawn.has(each))
      .map((each) => ({ address: each, depth: each.split('.').length - 1 }))
    headings.forEach((heading) => drawn.add(heading.address))

    const depth = address.split('.').length
    return {
      id: address,
      label: address,
      headings,
      ignoreFilter: true,
      items: byPlacement
        .get(address)!
        .map((workspace) => itemOf(workspace, false, indents[Math.min(depth, 4)])),
    }
  })
})

// Matched above against both the name and the placement, so the palette shows what it was given
// rather than narrowing it again on the name alone.
const groups = $computed(() =>
  tabbed && kind === 'associated'
    ? tree
    : [
        {
          id: 'workspaces',
          ignoreFilter: true,
          items: workspaces.map((workspace) => itemOf(workspace, true)),
        },
      ],
)

function onSelect(item: CommandPaletteItem & { workspace?: Workspace }) {
  if (item.workspace != null) {
    emit('select', item.workspace)
  }
}
</script>

<template>
  <div>
    <!-- A segmented control rather than underlined tabs, so it needs no rule of its own and sits
    inside the chooser's padding. -->
    <c-tabs
      v-if="tabbed"
      class="w-full p-2 pb-0"
      color="neutral"
      :content="false"
      :items="tabs"
      :model-value="kind"
      size="xs"
      :ui="{ list: 'w-full', trigger: 'flex-1 justify-center' }"
      variant="pill"
      @update:model-value="chooseKind"
    >
      <template #trailing="{ item }">
        <span class="text-xs tabular-nums text-muted">{{ item.count }}</span>
      </template>
    </c-tabs>
    <c-command-palette
      v-model:search-term="search"
      class="max-h-[210px]"
      :groups
      placeholder="Workspaces"
      @update:model-value="onSelect"
    >
      <template #group-label="{ group }">
        <div
          v-for="heading in (group as { headings?: Heading[] }).headings ?? []"
          :key="heading.address"
          class="flex items-center gap-1.5 py-0.5"
          :style="{ paddingLeft: `${heading.depth * 16}px` }"
        >
          <c-icon class="shrink-0 opacity-60" :name="icons.components" size="14" />
          <c-text variant="mono-xs">{{ heading.address }}</c-text>
        </div>
      </template>
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
          {{
            search.trim() === '' && tabbed
              ? `No ${kind} workspaces.`
              : (empty ?? 'No workspaces found.')
          }}
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
