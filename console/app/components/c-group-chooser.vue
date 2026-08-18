<script lang="ts">
// The blocks concatenate for linting, so this import cannot sort against the setup block's.
// eslint-disable-next-line imports/order
import type { Group } from '@/api/groups'

/** Whether `group` answers `search`, matched against its name and its description.

Groups are filtered here rather than by the engine, which offers no name query on them.
*/
export function groupMatches(group: Group, search: string): boolean {
  const text = search.trim().toLowerCase()
  if (text === '') {
    return true
  }

  return group.name.toLowerCase().includes(text) || group.description.toLowerCase().includes(text)
}
</script>

<script lang="ts" setup>
import type { CommandPaletteItem } from '@nuxt/ui'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

const emit = defineEmits<{
  select: [group: Group]
}>()

const {
  omit,
  disable,
  empty = null,
} = defineProps<{
  omit?: (group: Group) => boolean
  disable?: (group: Group) => boolean
  empty?: string | null
}>()

const engine = useEngine()

let search = $ref('')

const query = useQuery({
  queryKey: debouncedComputed(() => ['group-chooser', search], 100),
  queryFn: async () => {
    const groups = (await engine.groups.getAll()).filter((group) => groupMatches(group, search))
    return omit == null ? groups : groups.filter((group) => !omit(group))
  },
  placeholderData: (previous) => previous,
})

const groups = $computed(() => query.data.value ?? [])

// `groupMatches` has already answered the search, so the palette shows what it was given rather
// than narrowing it again against the same text.
const paletteGroups = $computed(() => [
  {
    id: 'groups',
    ignoreFilter: true,
    items: groups.map((group) => ({
      label: group.name,
      description: group.description,
      icon: icons.group,
      disabled: disable?.(group) ?? false,
      group,
    })),
  },
])

function onSelect(item: CommandPaletteItem & { group?: Group }) {
  if (item.group != null) {
    emit('select', item.group)
  }
}
</script>

<template>
  <c-command-palette
    v-model:search-term="search"
    class="max-h-[210px]"
    :groups="paletteGroups"
    :loading="query.isLoading.value"
    placeholder="Groups"
    @update:model-value="onSelect"
  >
    <template #empty>
      <c-text class="block p-2 text-center opacity-50" variant="body2">
        {{ empty ?? 'No groups found.' }}
      </c-text>
    </template>
  </c-command-palette>
</template>
