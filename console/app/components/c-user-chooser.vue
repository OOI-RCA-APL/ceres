<script lang="ts" setup>
import type { CommandPaletteItem } from '@nuxt/ui'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import type { User, UserFilter } from '@/api/users'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

const emit = defineEmits<{
  select: [user: User]
}>()

const {
  filter = null,
  omit,
  disable,
  empty = null,
} = defineProps<{
  /** Narrows what the engine returns before anything is typed, for a caller choosing from a
  subset of the users. */
  filter?: UserFilter | null
  omit?: (user: User) => boolean
  disable?: (user: User) => boolean
  empty?: string | null
}>()

const engine = useEngine()

let search = $ref('')

const query = useQuery({
  queryKey: debouncedComputed(() => ['user-chooser', search], 100),
  queryFn: async () => {
    const text = search.trim()

    const users = await engine.users.getAll({
      and: [
        ...(filter != null ? [filter] : []),
        { or: [{ username_contains: text }, { email_contains: text }] },
      ],
    })

    return omit == null ? users : users.filter((user) => !omit(user))
  },
  placeholderData: (previous) => previous,
})

const users = $computed(() => query.data.value ?? [])

// The engine has already matched the search, so the palette shows what it was given rather than
// narrowing it again against the same text.
const groups = $computed(() => [
  {
    id: 'users',
    ignoreFilter: true,
    items: users.map((user) => ({
      label: user.username,
      description: user.email,
      icon: icons.user,
      disabled: disable?.(user) ?? false,
      user,
    })),
  },
])

function onSelect(item: CommandPaletteItem & { user?: User }) {
  if (item.user != null) {
    emit('select', item.user)
  }
}
</script>

<template>
  <c-command-palette
    v-model:search-term="search"
    class="max-h-[210px]"
    :groups
    :loading="query.isLoading.value"
    placeholder="Users"
    @update:model-value="onSelect"
  >
    <template #empty>
      <c-text class="block p-2 text-center opacity-50" variant="body2">
        {{ empty ?? 'No users found.' }}
      </c-text>
    </template>
  </c-command-palette>
</template>
