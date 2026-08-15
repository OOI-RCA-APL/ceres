<script lang="ts" setup>
import { orderBy, uniqBy } from 'lodash-es'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

definePageMeta({ auth: 'admin' })

const engine = useEngine()

let search = $ref('')

// Two queries because the engine matches one field per filter, and a search box that only found
// usernames would miss a user looked up by their address.
const query = useQuery({
  queryKey: debouncedComputed(() => ['users', search], 100),
  queryFn: async () => {
    const [usernameMatches, emailMatches] = await Promise.all([
      engine.users.getAll({ username_contains: search }),
      engine.users.getAll({ email_contains: search }),
    ])

    return orderBy(uniqBy([...usernameMatches, ...emailMatches], 'id'), 'username')
  },
  placeholderData: (previous) => previous,
})

const users = $computed(() => query.data.value ?? [])
</script>

<template>
  <c-card-page title="Users">
    <template #header-append>
      <c-button :icon="icons.add" size="sm" to="/users/create" variant="ghost" />
    </template>
    <div class="p-4">
      <c-input
        v-model="search"
        autofocus
        class="mb-2 w-full"
        :icon="icons.search"
        :loading="query.isLoading.value"
        placeholder="Search"
        :spellcheck="false"
      >
        <template #trailing>
          <c-badge color="neutral" size="sm" variant="outline">{{ users.length }}</c-badge>
        </template>
      </c-input>
      <c-list class="h-[258px] overflow-y-auto">
        <c-list-item v-for="user in users" :key="user.id" :to="`/users/${user.id}`">
          <c-icon class="shrink-0" :name="user.admin ? icons.admin : icons.user" size="16" />
          <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ user.username }}</c-text>
          <c-text class="text-muted min-w-0 flex-1 truncate" variant="body2">
            {{ user.email }}
          </c-text>
        </c-list-item>
      </c-list>
    </div>
  </c-card-page>
</template>
