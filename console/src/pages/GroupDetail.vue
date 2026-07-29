<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { QMenu } from 'quasar'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useEngine } from '@/api/engine'
import { User } from '@/api/users'
import CardPageSection from '@/components/CardPageSection.vue'
import GroupPage from '@/components/GroupPage.vue'
import PermissionsSection from '@/components/PermissionsSection.vue'
import UserChooser from '@/components/UserChooser.vue'
import { useDialogs } from '@/dialogs'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'

const engine = useEngine()
const route = useRoute()
const router = useRouter()
const dialogs = useDialogs()
const notify = useNotify()

const id = $computed(() => route.params.id as string)

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
  () => allUsersQuery.data.value?.filter((user: User) => memberUserIds.has(user.id)) ?? []
)

let addMemberMenu = $ref<QMenu | null>(null)

async function addMember(user: User) {
  addMemberMenu?.hide()
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
      ok: { label: 'Remove', color: 'negative', flat: true },
      cancel: { label: 'Cancel', flat: true, color: 'grey' },
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
    .show({
      title: 'Delete Group',
      message: 'Permanently delete this group?',
      ok: { label: 'Delete', color: 'negative', flat: true },
      cancel: { label: 'Cancel', flat: true, color: 'grey' },
    })
    .onOk(async () => {
      await engine.groups.delete(id)
      notify.success('Group deleted.')
      router.push('/groups')
    })
}
</script>

<template>
  <group-page :id="id">
    <card-page-section :title="`Members (${memberUsers.length})`">
      <q-card-section>
        <q-list bordered class="rounded-borders" dense separator>
          <q-item v-for="user in memberUsers" :key="user.id" :to="`/users/${user.id}`">
            <q-item-section>
              <q-item-label>{{ user.username }}</q-item-label>
              <q-item-label caption>{{ user.email }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                color="negative"
                dense
                flat
                :icon="icons.delete"
                round
                size="sm"
                @click.prevent="promptRemoveMember(user)"
              />
            </q-item-section>
          </q-item>
          <q-item v-if="memberUsers.length === 0">
            <q-item-section>
              <q-item-label class="text-grey-6">No members.</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
        <div class="justify-center q-mt-sm row">
          <q-btn color="primary" dense :icon="icons.add" round size="10px" unelevated>
            <q-tooltip class="bg-primary text-white">Add Member</q-tooltip>
            <q-menu ref="addMemberMenu" anchor="top middle" :offset="[0, 12]" self="bottom middle">
              <q-card bordered :class="$style.addMenu" flat>
                <user-chooser
                  :omit="(user: User) => memberUserIds.has(user.id)"
                  @select="(user) => addMember(user)"
                />
              </q-card>
            </q-menu>
          </q-btn>
        </div>
      </q-card-section>
    </card-page-section>

    <permissions-section :subject-id="id" subject-type="group" />

    <card-page-section title="Danger Zone">
      <q-card-section>
        <q-btn
          class="full-width"
          color="negative"
          :icon="icons.delete"
          label="Delete Group"
          unelevated
          @click="promptDelete"
        />
      </q-card-section>
    </card-page-section>
  </group-page>
</template>

<style lang="scss" module>
.addMenu {
  min-width: 220px;
}
</style>
