<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'

const engine = useEngine()

const search = $ref('')
const query = useQuery({
  queryKey: debouncedComputed(() => ['users', search], 100),
  queryFn: async () =>
    engine.users.getAll({
      search,
      search_field: ['username', 'email'],
    }),
  placeholderData: keepPreviousData,
})

await query.suspense()
const users = $computed(() => query.data.value ?? [])
</script>

<template>
  <card-page title="Users">
    <template #header-append>
      <q-space />
      <q-btn flat :icon="icons.add" padding="none" round to="/users/create" />
    </template>
    <q-card-section>
      <q-input v-model="search" class="q-mb-md" dense :loading="query.isLoading.value" standout>
        <template #prepend>
          <q-icon :name="icons.search" />
        </template>
        <template #append>
          <q-chip :label="users.length" size="sm" />
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
