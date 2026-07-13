<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed } from 'vue'

import { useEngine } from '@/api/engine'
import { ComponentAccessLevel, PermissionTargetType } from '@/api/permissions'
import CardPageSection from '@/components/CardPageSection.vue'
import { useDialogs } from '@/dialogs'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'

const { subjectType, subjectId } = defineProps<{
  subjectType: 'user' | 'group'
  subjectId: string
}>()

const dialogs = useDialogs()
const engine = useEngine()
const notify = useNotify()

const permissionsQuery = useQuery({
  queryKey: computed(() => [`${subjectType}-permissions`, subjectId]),
  queryFn: () =>
    subjectType === 'user'
      ? engine.permissions.getUserPermissions(subjectId)
      : engine.permissions.getGroupPermissions(subjectId),
})

const permissions = $computed(() => permissionsQuery.data.value ?? [])

// Permissions a user inherits through group memberships, shown read-only since they are managed
// on the group's own page.
const inheritedQuery =
  subjectType === 'user'
    ? useQuery({
        queryKey: computed(() => ['user-inherited-permissions', subjectId]),
        queryFn: async () => {
          const memberships = await engine.groups.getMembershipsForUser(subjectId)
          const results = await Promise.all(
            memberships.map(async (membership) => {
              const [group, groupPermissions] = await Promise.all([
                engine.groups.get(membership.group_id),
                engine.permissions.getGroupPermissions(membership.group_id),
              ])

              return groupPermissions.map((permission) => ({
                ...permission,
                groupName: group?.name ?? membership.group_id,
              }))
            })
          )

          return results.flat()
        },
      })
    : null

const inheritedPermissions = $computed(() => inheritedQuery?.data.value ?? [])

let newPermissionTargetType = $ref<PermissionTargetType>('component')
let newPermissionTarget = $ref<string | null>(null)
let newPermissionLevel = $ref<ComponentAccessLevel>('view')

const componentAddresses = $computed(() => {
  const addresses = engine.components.all.map((component) => component.address.toString())

  // Move the root component to the end of the list.
  const rootIndex = addresses.indexOf('@')
  if (rootIndex !== -1) {
    addresses.push(...addresses.splice(rootIndex, 1))
  }

  return addresses
})

const allTags = $computed(() => {
  const tags = new Set<string>()
  for (const component of engine.components.all) {
    for (const tag of component.tags) {
      tags.add(tag)
    }
  }

  return [...tags].sort()
})

function onTargetTypeChange(type: PermissionTargetType) {
  newPermissionTargetType = type
  newPermissionTarget = null
}

async function addPermission() {
  if (newPermissionTarget == null) {
    return
  }

  const data = {
    target_type: newPermissionTargetType,
    target: newPermissionTarget,
    level: newPermissionLevel,
  }
  await guard(
    subjectType === 'user'
      ? engine.permissions.setUserPermission(subjectId, data)
      : engine.permissions.setGroupPermission(subjectId, data),
    () => {
      notify.error('Failed to add permission.')
    }
  )
  notify.success('Permission added.')
  newPermissionTarget = null
  await permissionsQuery.refetch()
}

function promptRemovePermission(targetType: PermissionTargetType, target: string) {
  const targetLabel = targetType === 'tag' ? `#${target}` : target
  dialogs
    .show({
      title: 'Remove Permission',
      message: `Remove the permission for "${targetLabel}"?`,
      ok: { label: 'Remove', color: 'negative', flat: true },
      cancel: { label: 'Cancel', flat: true, color: 'grey' },
    })
    .onOk(async () => {
      const data = { target_type: targetType, target }
      await guard(
        subjectType === 'user'
          ? engine.permissions.deleteUserPermission(subjectId, data)
          : engine.permissions.deleteGroupPermission(subjectId, data),
        () => {
          notify.error('Failed to remove permission.')
        }
      )
      notify.success('Permission removed.')
      await permissionsQuery.refetch()
    })
}
</script>

<template>
  <card-page-section :title="`Permissions (${permissions.length + inheritedPermissions.length})`">
    <q-card-section>
      <q-list bordered class="rounded-borders" dense separator>
        <q-item
          v-for="permission in permissions"
          :key="`${permission.target_type}-${permission.target}`"
        >
          <q-item-section>
            <q-item-label>
              {{ permission.target_type === 'tag' ? `#${permission.target}` : permission.target }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="items-center row">
              <q-chip
                class="q-px-sm"
                color="primary"
                dense
                :icon="icons[permission.level]"
                size="10px"
                text-color="white"
              >
                {{ upperFirst(permission.level) }}
              </q-chip>
              <q-btn
                class="q-ml-xs"
                color="negative"
                dense
                flat
                :icon="icons.delete"
                round
                size="sm"
                @click="promptRemovePermission(permission.target_type, permission.target)"
              />
            </div>
          </q-item-section>
        </q-item>
        <q-item
          v-for="permission in inheritedPermissions"
          :key="`${permission.group_id}-${permission.target_type}-${permission.target}`"
          :to="`/groups/${permission.group_id}`"
        >
          <q-item-section>
            <q-item-label>
              {{ permission.target_type === 'tag' ? `#${permission.target}` : permission.target }}
            </q-item-label>
            <q-item-label caption>From group "{{ permission.groupName }}"</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-chip
              class="q-px-sm"
              color="primary"
              dense
              :icon="icons[permission.level]"
              size="10px"
              text-color="white"
            >
              {{ upperFirst(permission.level) }}
            </q-chip>
          </q-item-section>
        </q-item>
        <q-item v-if="permissions.length === 0 && inheritedPermissions.length === 0">
          <q-item-section>
            <q-item-label class="text-grey-6">No permissions.</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <div class="justify-center q-mt-sm row">
        <q-btn color="primary" dense :icon="icons.add" round size="10px" unelevated>
          <q-tooltip class="bg-primary text-white">Add Permission</q-tooltip>
          <q-menu anchor="top middle" :offset="[0, 12]" self="bottom middle">
            <q-card bordered :class="$style.addMenu" flat>
              <div class="column q-col-gutter-sm q-pa-sm">
                <q-select
                  v-model="newPermissionLevel"
                  dense
                  label="Can"
                  :option-label="(option: string) => upperFirst(option)"
                  :options="['view', 'operate', 'manage']"
                  options-dense
                  outlined
                />
                <q-select
                  dense
                  label="Type"
                  :model-value="newPermissionTargetType"
                  :option-label="(option: string) => upperFirst(option)"
                  :options="['component', 'tag']"
                  options-dense
                  outlined
                  @update:model-value="onTargetTypeChange"
                />
                <q-select
                  v-model="newPermissionTarget"
                  dense
                  :label="upperFirst(newPermissionTargetType)"
                  :options="newPermissionTargetType === 'component' ? componentAddresses : allTags"
                  options-dense
                  outlined
                />
                <div>
                  <q-btn
                    v-close-popup
                    class="full-width"
                    color="primary"
                    dense
                    :disable="newPermissionTarget == null"
                    label="Add"
                    @click="addPermission"
                  />
                </div>
              </div>
            </q-card>
          </q-menu>
        </q-btn>
      </div>
    </q-card-section>
  </card-page-section>
</template>

<style lang="scss" module>
.addMenu {
  min-width: 220px;
}
</style>
