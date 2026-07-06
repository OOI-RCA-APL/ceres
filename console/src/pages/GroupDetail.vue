<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
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

const groupQuery = useQuery({
  queryKey: computed(() => ['group', id]),
  queryFn: () => engine.groups.get(id),
})

const membersQuery = useQuery({
  queryKey: computed(() => ['group-members', id]),
  queryFn: () => engine.groups.getMembers(id),
})

const permissionsQuery = useQuery({
  queryKey: computed(() => ['group-permissions', id]),
  queryFn: () => engine.permissions.getGroupPermissions(id),
})

await groupQuery.suspense()

const group = $computed(() => groupQuery.data.value)
const members = $computed(() => membersQuery.data.value ?? [])
const permissions = $computed(() => permissionsQuery.data.value ?? [])

const allUsers = useQuery({
  queryKey: ['all-users'],
  queryFn: () => engine.users.getAll(),
})

const newPermTargetType = ref<'component' | 'tag'>('component')
const newPermTarget = ref('')
const newPermLevel = ref<'view' | 'operate' | 'manage'>('view')

async function addMember(userId: string) {
  await guard(engine.groups.addMember(id, userId), () => {
    notify.error('Failed to add member.')
  })
  notify.success('Member added.')
  await membersQuery.refetch()
}

async function removeMember(userId: string) {
  await guard(engine.groups.removeMember(id, userId), () => {
    notify.error('Failed to remove member.')
  })
  notify.success('Member removed.')
  await membersQuery.refetch()
}

async function addPermission() {
  if (newPermTarget.value.trim() === '') {
    return
  }

  await guard(
    engine.permissions.setGroupPermission(id, {
      target_type: newPermTargetType.value,
      target: newPermTarget.value.trim(),
      level: newPermLevel.value,
    }),
    () => {
      notify.error('Failed to add permission.')
    }
  )
  notify.success('Permission added.')
  newPermTarget.value = ''
  await permissionsQuery.refetch()
}

async function removePermission(targetType: string, target: string) {
  await guard(
    engine.permissions.deleteGroupPermission(id, {
      target_type: targetType as 'component' | 'tag',
      target,
    }),
    () => {
      notify.error('Failed to remove permission.')
    }
  )
  notify.success('Permission removed.')
  await permissionsQuery.refetch()
}

function promptDelete() {
  if (group == null) {
    return
  }

  dialogs
    .show({
      title: 'Delete Group',
      message: `Permanently delete group "${group.name}"?`,
      ok: { label: 'Delete', color: 'negative', flat: true },
      cancel: { label: 'Cancel', flat: true, color: 'grey' },
    })
    .onOk(async () => {
      await engine.groups.delete(id)
      notify.success(`Group "${group.name}" deleted.`)
      router.push('/groups')
    })
}
</script>

<template>
  <card-page :title="group?.name ?? 'Group'">
    <template #header-append>
      <q-space />
      <q-btn color="negative" flat :icon="icons.delete" round size="sm" @click="promptDelete" />
    </template>

    <q-card-section v-if="group == null">
      <div class="text-grey-6">Group not found.</div>
    </q-card-section>

    <template v-else>
      <q-card-section v-if="group.description">
        <div class="text-body2 text-grey-7">{{ group.description }}</div>
      </q-card-section>

      <q-separator />

      <q-card-section>
        <div class="q-mb-xs text-subtitle2">Members</div>
        <q-list bordered dense separator>
          <q-item v-for="member in members" :key="member.user_id">
            <q-item-section>
              <q-item-label>{{ member.user_id }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                color="negative"
                dense
                flat
                :icon="icons.delete"
                round
                size="sm"
                @click="removeMember(member.user_id)"
              />
            </q-item-section>
          </q-item>
          <q-item v-if="members.length === 0">
            <q-item-section>
              <q-item-label class="text-grey-6">No members.</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
        <div class="q-mt-sm">
          <q-select
            dense
            label="Add member"
            :model-value="null"
            :option-label="(u: any) => u.username"
            :option-value="(u: any) => u.id"
            :options="allUsers.data.value ?? []"
            outlined
            @update:model-value="(u: any) => { if (u) { addMember(u.id) } }"
          />
        </div>
      </q-card-section>

      <q-separator />

      <q-card-section>
        <div class="q-mb-xs text-subtitle2">Permissions</div>
        <q-list bordered dense separator>
          <q-item v-for="perm in permissions" :key="`${perm.target_type}-${perm.target}`">
            <q-item-section>
              <q-item-label>
                <q-chip dense :label="perm.target_type" outline size="sm" />
                {{ perm.target }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div class="items-center row">
                <q-chip color="primary" dense :label="upperFirst(perm.level)" text-color="white" />
                <q-btn
                  class="q-ml-xs"
                  color="negative"
                  dense
                  flat
                  :icon="icons.delete"
                  round
                  size="sm"
                  @click="removePermission(perm.target_type, perm.target)"
                />
              </div>
            </q-item-section>
          </q-item>
          <q-item v-if="permissions.length === 0">
            <q-item-section>
              <q-item-label class="text-grey-6">No permissions.</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
        <div class="items-end q-gutter-sm q-mt-sm row">
          <q-select
            v-model="newPermTargetType"
            class="col-2"
            dense
            label="Type"
            :options="['component', 'tag']"
            outlined
          />
          <q-input
            v-model="newPermTarget"
            class="col-grow"
            dense
            label="Target"
            outlined
          />
          <q-select
            v-model="newPermLevel"
            class="col-2"
            dense
            label="Level"
            :options="['view', 'operate', 'manage']"
            outlined
          />
          <q-btn color="primary" dense flat label="Add" @click="addPermission" />
        </div>
      </q-card-section>
    </template>
  </card-page>
</template>
