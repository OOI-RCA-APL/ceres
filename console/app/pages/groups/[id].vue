<script lang="ts" setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import type { User } from '@/api/users'
import { useDialogs } from '@/dialogs'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'

definePageMeta({ auth: 'admin' })

const engine = useEngine()
const route = useRoute()
const navigation = useNavigation()
const dialogs = useDialogs()
const notify = useNotify()

const id = $computed(() => String(route.params.id))

const membersQuery = useQuery({
  queryKey: computed(() => ['group-members', id]),
  queryFn: () => engine.groups.getMembers(id),
})

const members = $computed(() => membersQuery.data.value ?? [])

const allUsersQuery = useQuery({
  queryKey: ['all-users'],
  queryFn: () => engine.users.getAll(),
})

const memberUserIds = $computed(() => new Set(members.map((membership) => membership.user_id)))

const memberUsers = $computed(
  () => allUsersQuery.data.value?.filter((user) => memberUserIds.has(user.id)) ?? [],
)

let isAddingMember = $ref(false)

async function addMember(user: User) {
  isAddingMember = false
  await guard(engine.groups.addMember(id, user.id), () => {
    notify.error('Failed to add member.')
  })
  notify.success(`Added "${user.username}".`)
  await membersQuery.refetch()
  await allUsersQuery.refetch()
}

function promptRemoveMember(user: User) {
  dialogs
    .show({
      title: 'Remove Member',
      message: `Remove "${user.username}" from this group?`,
      okLabel: 'Remove',
      okColor: 'error',
    })
    .onOk(async () => {
      await guard(engine.groups.removeMember(id, user.id), () => {
        notify.error('Failed to remove member.')
      })
      notify.success(`Removed "${user.username}".`)
      await membersQuery.refetch()
    })
}

function promptDelete() {
  dialogs
    .delete({ title: 'Delete Group', message: 'Permanently delete this group?' })
    .onOk(async () => {
      await engine.groups.delete(id)
      notify.success('Group deleted.')
      await navigation.go('/groups')
    })
}

const rowClass = 'flex items-center gap-2 px-3 py-1.5'
</script>

<template>
  <c-group-page :id>
    <c-card-page-section :title="`Members (${memberUsers.length})`">
      <div class="p-4">
        <div class="divide-default divide-y rounded-md border border-default">
          <nuxt-link
            v-for="user in memberUsers"
            :key="user.id"
            :class="[rowClass, 'hover:bg-elevated']"
            :to="`/users/${user.id}`"
          >
            <span class="min-w-0 grow">
              <c-text class="block truncate" variant="body2">{{ user.username }}</c-text>
              <c-text class="block truncate" variant="description">{{ user.email }}</c-text>
            </span>
            <c-button
              color="error"
              :icon="icons.delete"
              size="xs"
              variant="ghost"
              @click.prevent="promptRemoveMember(user)"
            />
          </nuxt-link>
          <div v-if="memberUsers.length === 0" :class="rowClass">
            <c-text class="text-muted block" variant="body2">No members.</c-text>
          </div>
        </div>
        <div class="mt-2 flex justify-center">
          <c-popover
            v-model:open="isAddingMember"
            :content="{ side: 'top' }"
            :ui="{ content: 'w-[220px]' }"
          >
            <c-tooltip text="Add Member">
              <c-button :icon="icons.add" size="xs" />
            </c-tooltip>
            <template #content>
              <c-user-chooser
                :omit="(user: User) => memberUserIds.has(user.id)"
                @select="addMember"
              />
            </template>
          </c-popover>
        </div>
      </div>
    </c-card-page-section>

    <c-permissions-section :subject-id="id" subject-type="group" />

    <c-card-page-section title="Danger Zone">
      <div class="p-4">
        <c-button
          block
          color="error"
          :icon="icons.delete"
          label="Delete Group"
          @click="promptDelete"
        />
      </div>
    </c-card-page-section>
  </c-group-page>
</template>
