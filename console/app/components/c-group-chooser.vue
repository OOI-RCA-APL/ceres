<script lang="ts">
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

function submitFirst() {
  const first = groups[0]
  if (first != null) {
    emit('select', first)
  }
}
</script>

<template>
  <div class="p-2">
    <c-input
      v-model="search"
      autofocus
      class="mb-2 w-full"
      :icon="icons.search"
      placeholder="Groups"
      size="sm"
      :spellcheck="false"
      @keyup.enter="submitFirst"
    />
    <c-text v-if="groups.length === 0" class="block p-2 text-center opacity-50" variant="body2">
      {{ empty ?? 'No groups found.' }}
    </c-text>
    <c-list v-else class="max-h-[120px] overflow-y-auto">
      <c-list-item
        v-for="group in groups"
        :key="group.id"
        :class="groups.length === 1 && 'bg-elevated'"
        :disabled="disable?.(group) ?? false"
        @click="emit('select', group)"
      >
        <c-icon class="shrink-0" :name="icons.group" size="18" />
        <span class="min-w-0">
          <c-text class="block truncate" variant="body2">{{ group.name }}</c-text>
          <c-text v-if="group.description" class="block truncate" variant="description">
            {{ group.description }}
          </c-text>
        </span>
      </c-list-item>
    </c-list>
  </div>
</template>
