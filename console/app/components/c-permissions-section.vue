<script lang="ts" setup>
import { upperFirst } from 'lodash-es'
import { computed } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import type { ComponentAccessLevel, PermissionGrant, PermissionTargetType } from '@/api/permissions'
import { useDialogs } from '@/dialogs'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { permissionTargetLabel, resolveEffectiveAccess, targetTypeLabel } from '@/permissions'

const { subjectType, subjectId } = defineProps<{
  subjectType: 'user' | 'group'
  subjectId: string
}>()

const engine = useEngine()
const dialogs = useDialogs()
const notify = useNotify()

const permissionsQuery = useQuery({
  queryKey: computed(() => [`${subjectType}-permissions`, subjectId]),
  // Narrowed to what the two kinds share, since the section shows a grant and not who holds it.
  queryFn: (): Promise<PermissionGrant[]> =>
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
            }),
          )

          return results.flat()
        },
      })
    : null

const inheritedPermissions = $computed(() => inheritedQuery?.data.value ?? [])

// Effective access is resolved per user, so there is no equivalent for a group on its own.
const effectiveQuery =
  subjectType === 'user'
    ? useQuery({
        queryKey: computed(() => ['user-effective-access', subjectId]),
        queryFn: () => engine.permissions.getAllEffectiveAccess(subjectId),
      })
    : null

const groupNames = $computed(() => {
  const names = new Map<string, string>()
  for (const permission of inheritedPermissions) {
    if (permission.group_id != null) {
      names.set(permission.group_id, permission.groupName)
    }
  }

  return names
})

const effectiveAccess = $computed(() =>
  resolveEffectiveAccess(
    engine.components.all.map((component) => component.address.toString()),
    effectiveQuery?.data.value ?? [],
    groupNames,
  ),
)

const grantedCount = $computed(() => effectiveAccess.filter((entry) => entry.level != null).length)

const componentAddresses = $computed(() =>
  engine.components.all.map((component) => component.address.toString()),
)

const allTags = $computed(() => {
  const tags = new Set<string>()
  for (const component of engine.components.all) {
    for (const tag of component.tags) {
      tags.add(tag)
    }
  }

  return [...tags].sort()
})

let isAddingPermission = $ref(false)
let newPermissionTargetType = $ref<PermissionTargetType>('component')
let newPermissionTarget = $ref<string | undefined>(undefined)
let newPermissionLevel = $ref<ComponentAccessLevel>('view')

const levelItems = (['view', 'operate', 'manage'] as const).map((level) => ({
  label: upperFirst(level),
  value: level,
}))

const targetTypeItems = (['component', 'tag', 'all'] as const).map((type) => ({
  label: targetTypeLabel(type),
  value: type,
}))

const targetItems = $computed(() =>
  newPermissionTargetType === 'component' ? componentAddresses : allTags,
)

// A target chosen under one type means nothing under another, so switching clears it. The empty
// string stands in for the target "all components" does not have.
function onTargetTypeChange(type: PermissionTargetType) {
  newPermissionTargetType = type
  newPermissionTarget = type === 'all' ? '' : undefined
}

/** Refresh everything a grant changes: the list itself, what it resolves to, and the access map
the rest of the console is drawn from. */
async function refreshAfterChange() {
  await permissionsQuery.refetch()
  await effectiveQuery?.refetch()
  await guard(engine.access.refresh(), () => {
    notify.error('Failed to refresh access.')
  })
}

async function addPermission() {
  if (newPermissionTargetType !== 'all' && newPermissionTarget == null) {
    return
  }

  isAddingPermission = false
  const data = {
    target_type: newPermissionTargetType,
    target: newPermissionTarget ?? '',
    level: newPermissionLevel,
  }
  const request: Promise<PermissionGrant> =
    subjectType === 'user'
      ? engine.permissions.setUserPermission(subjectId, data)
      : engine.permissions.setGroupPermission(subjectId, data)
  await guard(request, () => {
    notify.error('Failed to add permission.')
  })
  notify.success('Permission added.')
  newPermissionTarget = undefined
  await refreshAfterChange()
}

function promptRemovePermission(targetType: PermissionTargetType, target: string) {
  const targetLabel = permissionTargetLabel({ target_type: targetType, target })
  dialogs
    .show({
      title: 'Remove Permission',
      message: `Remove the permission for "${targetLabel}"?`,
      okLabel: 'Remove',
      okColor: 'error',
    })
    .onOk(async () => {
      const data = { target_type: targetType, target }
      await guard(
        subjectType === 'user'
          ? engine.permissions.deleteUserPermission(subjectId, data)
          : engine.permissions.deleteGroupPermission(subjectId, data),
        () => {
          notify.error('Failed to remove permission.')
        },
      )
      notify.success('Permission removed.')
      await refreshAfterChange()
    })
}

const rowClass = 'flex items-center gap-2 px-3 py-1.5'
const listClass = 'divide-y divide-default rounded-md border border-default'
</script>

<template>
  <c-card-page-section :title="`Permissions (${permissions.length + inheritedPermissions.length})`">
    <div class="p-4">
      <div :class="listClass">
        <div
          v-for="permission in permissions"
          :key="`${permission.target_type}-${permission.target}`"
          :class="rowClass"
        >
          <span class="grow truncate text-sm">{{ permissionTargetLabel(permission) }}</span>
          <c-badge color="primary" :icon="icons[permission.level]" size="sm">
            {{ upperFirst(permission.level) }}
          </c-badge>
          <c-button
            color="error"
            :icon="icons.delete"
            size="xs"
            variant="ghost"
            @click="promptRemovePermission(permission.target_type, permission.target)"
          />
        </div>
        <nuxt-link
          v-for="permission in inheritedPermissions"
          :key="`${permission.group_id}-${permission.target_type}-${permission.target}`"
          :class="[rowClass, 'hover:bg-elevated']"
          :to="`/groups/${permission.group_id}`"
        >
          <span class="min-w-0 grow">
            <span class="block truncate text-sm">{{ permissionTargetLabel(permission) }}</span>
            <c-text class="block truncate" variant="description">
              From group "{{ permission.groupName }}".
            </c-text>
          </span>
          <c-badge color="primary" :icon="icons[permission.level]" size="sm">
            {{ upperFirst(permission.level) }}
          </c-badge>
        </nuxt-link>
        <div v-if="permissions.length === 0 && inheritedPermissions.length === 0" :class="rowClass">
          <span class="block">
            <c-text class="text-muted block" variant="body2">No permissions granted.</c-text>
            <c-text class="block" variant="description">
              Components may still be reachable through their default access level.
            </c-text>
          </span>
        </div>
      </div>
      <div class="mt-2 flex justify-center">
        <c-popover
          v-model:open="isAddingPermission"
          :content="{ side: 'top' }"
          :ui="{ content: 'w-[240px]' }"
        >
          <c-tooltip text="Add Permission">
            <c-button :icon="icons.add" size="xs" />
          </c-tooltip>
          <template #content>
            <div class="flex flex-col gap-2 p-2">
              <c-form-field label="Can">
                <c-select v-model="newPermissionLevel" class="w-full" :items="levelItems" />
              </c-form-field>
              <c-form-field label="Type">
                <c-select
                  class="w-full"
                  :items="targetTypeItems"
                  :model-value="newPermissionTargetType"
                  @update:model-value="onTargetTypeChange"
                />
              </c-form-field>
              <c-form-field
                v-if="newPermissionTargetType !== 'all'"
                :label="targetTypeLabel(newPermissionTargetType)"
              >
                <c-select-menu v-model="newPermissionTarget" class="w-full" :items="targetItems" />
              </c-form-field>
              <c-button
                block
                :disabled="newPermissionTargetType !== 'all' && newPermissionTarget == null"
                label="Add"
                @click="addPermission"
              />
            </div>
          </template>
        </c-popover>
      </div>
    </div>
  </c-card-page-section>

  <c-card-page-section v-if="subjectType === 'user'" :title="`Effective Access (${grantedCount})`">
    <div class="p-4">
      <c-text class="text-muted mb-2 block" variant="description">
        What this user can actually do, after grants, group memberships, and each component's
        default access level are resolved together.
      </c-text>
      <div :class="listClass">
        <component
          :is="entry.groupId != null ? 'nuxt-link' : 'div'"
          v-for="entry in effectiveAccess"
          :key="entry.address"
          :class="[rowClass, entry.groupId != null && 'hover:bg-elevated']"
          :to="entry.groupId != null ? `/groups/${entry.groupId}` : undefined"
        >
          <span class="min-w-0 grow">
            <c-text class="block truncate" variant="mono-sm">{{ entry.address }}</c-text>
            <c-text class="block truncate" variant="description">
              {{ entry.source ?? 'No access.' }}
            </c-text>
          </span>
          <c-badge v-if="entry.level != null" color="primary" :icon="icons[entry.level]" size="sm">
            {{ upperFirst(entry.level) }}
          </c-badge>
          <c-icon v-else class="text-muted size-4" :name="icons.locked" />
        </component>
        <div v-if="effectiveAccess.length === 0" :class="rowClass">
          <c-text class="text-muted block" variant="body2">No components.</c-text>
        </div>
      </div>
    </div>
  </c-card-page-section>
</template>
