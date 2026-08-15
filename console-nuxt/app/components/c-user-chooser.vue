<script lang="ts" setup>
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

function submitFirst() {
  const first = users[0]
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
      placeholder="Users"
      size="sm"
      :spellcheck="false"
      @keyup.enter="submitFirst"
    />
    <c-text v-if="users.length === 0" class="block p-2 text-center opacity-50" variant="body2">
      {{ empty ?? 'No users found.' }}
    </c-text>
    <div
      v-else
      class="max-h-[120px] divide-y divide-default overflow-y-auto rounded-md border border-default"
    >
      <button
        v-for="user in users"
        :key="user.id"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-elevated disabled:opacity-50"
        :class="users.length === 1 && 'bg-elevated'"
        :disabled="disable?.(user) ?? false"
        type="button"
        @click="emit('select', user)"
      >
        <c-icon class="shrink-0" :name="icons.user" size="18" />
        <span class="min-w-0">
          <c-text class="block truncate" variant="body2">{{ user.username }}</c-text>
          <c-text class="block truncate" variant="description">{{ user.email }}</c-text>
        </span>
      </button>
    </div>
  </div>
</template>
