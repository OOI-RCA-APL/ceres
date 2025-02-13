<script lang="ts" setup>
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { uniqBy, orderBy } from 'lodash-es'

import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

const engine = useEngine()

const search = $ref('')
const query = useQuery({
  queryKey: debouncedComputed(() => ['users', search], 100),
  queryFn: async () => {
    const [usernameMatches, emailMatches] = await Promise.all([
      engine.users.getAll({
        username_contains: search,
      }),
      engine.users.getAll({
        email_contains: search,
      }),
    ])

    return orderBy(uniqBy([...usernameMatches, ...emailMatches], 'id'), 'username')
  },
  placeholderData: keepPreviousData,
})

await query.suspense()
const users = $computed(() => query.data.value ?? [])
</script>

<template>
  <card-page title="Users">
    <template #header-append>
      <q-space />
      <q-btn flat :icon="icons.add" padding="none" round size="12px" to="/users/create" />
    </template>
    <q-card-section>
      <q-input
        v-model="search"
        autofocus
        class="q-mb-sm"
        dense
        :loading="query.isLoading.value"
        outlined
      >
        <template #prepend>
          <q-icon :name="icons.search" />
        </template>
        <template #append>
          <q-chip :label="users.length" outline size="sm" />
        </template>
      </q-input>
      <q-card bordered :class="$style.list" flat>
        <q-list class="fit scroll" dense separator>
          <q-item v-for="user in users" :key="user.id" :to="`/users/${user.id}`">
            <q-item-section avatar>
              <q-icon :name="icons.user" />
            </q-item-section>
            <q-item-section>
              {{ user.username }}
            </q-item-section>
            <q-item-section>
              <span class="text-grey-6">{{ user.email }}</span>
            </q-item-section>
          </q-item>
          <q-separator />
        </q-list>
      </q-card>
    </q-card-section>
  </card-page>
</template>

<style lang="scss" module>
.list {
  height: 258px;
  overflow-y: auto;
}
</style>
