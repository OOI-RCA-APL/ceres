<script lang="ts" setup>
import { useUsers } from '@/api/users'
import CardPage from '@/components/CardPage.vue'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'
import { useQuery } from '@tanstack/vue-query'

const store = useUsers()

const search = $ref('')
const query = useQuery({
  queryKey: ['users'],
  queryFn: store.getAll,
})

await query.suspense()
const users = debouncedComputed(
  () =>
    query.data.value?.filter(
      (user) => user.username.includes(search) || user.email.includes(search)
    ) ?? [],
  100
)
</script>

<template>
  <card-page title="Users">
    <template #header-append>
      <q-space />
      <q-btn flat :icon="icons.add" padding="none" round to="/users/create" />
    </template>
    <q-card-section>
      <q-input v-model="search" class="q-mb-md" dense standout>
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
