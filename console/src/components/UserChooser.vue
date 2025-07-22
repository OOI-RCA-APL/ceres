<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { User, UserFilter } from '@/api/users'
import { debouncedComputed } from '@/utilities'

defineEmits<{
  (emit: 'select', user: User): void
}>()

const { filter, omit, empty } = defineProps<{
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
    const query = search.trim()

    let users = await engine.users.getAll({
      and: [
        ...(filter != null ? [filter] : []),
        {
          or: [{ username_contains: query }, { email_contains: query }],
        },
      ],
    })

    if (omit != null) {
      users = users.filter((user) => !omit(user))
    }

    return users
  },
  placeholderData: (previous) => previous,
})

const users = $computed(() => query.data.value ?? [])
</script>

<template>
  <div class="q-pa-sm">
    <q-input v-model="search" class="q-mb-sm" dense outlined :spellcheck="false">
      <template #prepend>
        <q-icon name="search" />
      </template>
    </q-input>
    <q-card bordered flat>
      <div v-if="users.length === 0" :class="[$style.emptyMessageText, 'q-pa-sm']">
        {{ empty ?? 'No users found.' }}
      </div>
      <q-list v-else :class="[$style.list, 'scroll']" dense>
        <q-item
          v-for="user in users"
          :key="user.id"
          clickable
          :disable="disable?.(user) ?? false"
          @click="$emit('select', user)"
        >
          <q-item-section>
            <q-item-label>{{ user.username }}</q-item-label>
            <q-item-label caption>{{ user.email }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>
  </div>
</template>

<style lang="scss" module>
.list {
  max-height: calc(40px * 3);
}

.emptyMessageText {
  text-align: center;
  font-size: 13px;
  opacity: 0.5;
}
</style>
