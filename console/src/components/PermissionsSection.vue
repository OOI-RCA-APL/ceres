<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed } from 'vue'

import { useAccess } from '@/api/access'
import { useEngine } from '@/api/engine'
import {
  AccessSource,
  ComponentAccessLevel,
  ComponentEffectiveAccess,
  PermissionTargetType,
} from '@/api/permissions'
import CardPageSection from '@/components/CardPageSection.vue'
import { useDialogs } from '@/dialogs'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'

const { subjectType, subjectId } = defineProps<{
  subjectType: 'user' | 'group'
  subjectId: string
}>()

const access = useAccess()
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

// Effective access is resolved per user, so there is no equivalent for a group on its own.
const effectiveQuery =
  subjectType === 'user'
    ? useQuery({
        queryKey: computed(() => ['user-effective-access', subjectId]),
        queryFn: () => engine.permissions.getAllEffectiveAccess(subjectId),
      })
    : null

const effectiveEntries = $computed(() => {
  const entries = new Map<string, ComponentEffectiveAccess>()
  for (const entry of effectiveQuery?.data.value ?? []) {
    entries.set(entry.address, entry)
  }

  return entries
})

// The server reports which input conferred each level, so nothing here has to be inferred.
// The trailing period is appended in `sourceLabel` so group suffixes compose cleanly.
const SOURCE_LABELS: Record<AccessSource, string> = {
  admin: 'From administrator status',
  default: 'From default access level',
  component: 'Granted on this component',
  tag: 'Granted through a tag',
  all: 'Granted on all components',
}

const groupNames = $computed(() => {
  const names = new Map<string, string>()
  for (const permission of inheritedPermissions) {
    if (permission.group_id != null) {
      names.set(permission.group_id, permission.groupName)
    }
  }

  return names
})

/** Label a resolved level, naming the group when a group's grant is what conferred it. */
function sourceLabel(entry: ComponentEffectiveAccess): string {
  const label = SOURCE_LABELS[entry.source]
  if (entry.origin !== 'group' || entry.group_id == null) {
    return `${label}.`
  }

  const name = groupNames.get(entry.group_id)
  return name == null ? `${label}, through a group.` : `${label}, from group "${name}".`
}

const effectiveAccess = $computed(() =>
  engine.components.all
    .map((component) => {
      const address = component.address.toString()
      const entry = effectiveEntries.get(address)
      return {
        address,
        level: entry?.level ?? null,
        source: entry == null ? null : sourceLabel(entry),
        groupId: entry?.origin === 'group' ? entry.group_id ?? null : null,
      }
    })
    .sort((first, second) => first.address.localeCompare(second.address))
)

async function refreshEffectiveAccess() {
  await effectiveQuery?.refetch()
}

let newPermissionTargetType = $ref<PermissionTargetType>('component')
let newPermissionTarget = $ref<string | null>(null)
let newPermissionLevel = $ref<ComponentAccessLevel>('view')

const componentAddresses = $computed(() =>
  engine.components.all.map((component) => component.address.toString())
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

function targetTypeLabel(type: string): string {
  return type === 'all' ? 'All components' : upperFirst(type)
}

function permissionTargetLabel(permission: {
  target_type?: PermissionTargetType
  target?: string
}) {
  if (permission.target_type === 'all') {
    return 'All components'
  } else if (permission.target_type === 'tag') {
    return `#${permission.target}`
  }

  return permission.target
}

function onTargetTypeChange(type: PermissionTargetType) {
  newPermissionTargetType = type
  newPermissionTarget = type === 'all' ? '' : null
}

async function addPermission() {
  if (newPermissionTargetType !== 'all' && newPermissionTarget == null) {
    return
  }

  const data = {
    target_type: newPermissionTargetType,
    target: newPermissionTarget ?? '',
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
  await refreshEffectiveAccess()
  await guard(access.refresh(), () => {
    notify.error('Failed to refresh access.')
  })
}

function promptRemovePermission(targetType: PermissionTargetType, target: string) {
  const targetLabel = permissionTargetLabel({ target_type: targetType, target })
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
      await refreshEffectiveAccess()
      await guard(access.refresh(), () => {
        notify.error('Failed to refresh access.')
      })
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
          :class="$style.item"
        >
          <q-item-section>
            <q-item-label>
              {{ permissionTargetLabel(permission) }}
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
          :class="$style.item"
          :to="`/groups/${permission.group_id}`"
        >
          <q-item-section>
            <q-item-label>
              {{ permissionTargetLabel(permission) }}
            </q-item-label>
            <q-item-label caption>From group "{{ permission.groupName }}".</q-item-label>
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
        <q-item
          v-if="permissions.length === 0 && inheritedPermissions.length === 0"
          :class="$style.item"
        >
          <q-item-section>
            <q-item-label class="text-grey-6">No permissions granted.</q-item-label>
            <q-item-label caption>
              Components may still be reachable through their default access level.
            </q-item-label>
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
                  :option-label="targetTypeLabel"
                  :options="['component', 'tag', 'all']"
                  options-dense
                  outlined
                  @update:model-value="onTargetTypeChange"
                />
                <q-select
                  v-if="newPermissionTargetType !== 'all'"
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
                    :disable="newPermissionTargetType !== 'all' && newPermissionTarget == null"
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
  <card-page-section
    v-if="subjectType === 'user'"
    :title="`Effective Access (${effectiveAccess.filter((entry) => entry.level != null).length})`"
  >
    <q-card-section>
      <div class="q-mb-sm text-grey-6" :class="$style.caption">
        What this user can actually do, after grants, group memberships, and each component's
        default access level are resolved together.
      </div>
      <q-list bordered class="rounded-borders" dense separator>
        <q-item
          v-for="entry in effectiveAccess"
          :key="entry.address"
          :class="$style.item"
          :to="entry.groupId != null ? `/groups/${entry.groupId}` : undefined"
        >
          <q-item-section>
            <q-item-label>{{ entry.address }}</q-item-label>
            <q-item-label caption>{{ entry.source ?? 'No access.' }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-chip
              v-if="entry.level != null"
              class="q-px-sm"
              color="primary"
              dense
              :icon="icons[entry.level]"
              size="10px"
              text-color="white"
            >
              {{ upperFirst(entry.level) }}
            </q-chip>
            <q-icon v-else class="text-grey-6" :name="icons.locked" size="16px" />
          </q-item-section>
        </q-item>
        <q-item v-if="effectiveAccess.length === 0" :class="$style.item">
          <q-item-section>
            <q-item-label class="text-grey-6">No components.</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card-section>
  </card-page-section>
</template>

<style lang="scss" module>
.item {
  padding-top: 6px;
  padding-bottom: 6px;
}

.caption {
  font-size: 12px;
  line-height: 1.4;
}

.addMenu {
  min-width: 220px;
}
</style>
