<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { upperFirst } from 'lodash-es'
import { computed } from 'vue'

import { useAccess } from '@/api/access'
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

const effectiveLevels = $computed(() => {
  const levels = new Map<string, ComponentAccessLevel>()
  for (const entry of effectiveQuery?.data.value ?? []) {
    levels.set(entry.address, entry.level)
  }

  return levels
})

const LEVEL_RANK: Record<ComponentAccessLevel, number> = { view: 0, operate: 1, manage: 2 }

type MatchablePermission = {
  target_type?: PermissionTargetType
  target?: string
  level?: ComponentAccessLevel
}

/** Return an address and each of its ancestors, from the component up to its top-level parent. */
function addressChain(address: string): string[] {
  const parts = address.replace(/^@/, '').split('.')
  return parts.map((_, index) => `@${parts.slice(0, index + 1).join('.')}`).reverse()
}

/** Collect the tags on a component and every ancestor above it. */
function inheritedTags(address: string): Set<string> {
  const tags = new Set<string>()
  for (const ancestor of addressChain(address)) {
    const component = engine.components.get(ancestor)
    for (const tag of component?.tags ?? []) {
      tags.add(tag)
    }
  }

  return tags
}

/** Return the highest level any of `candidates` confers on `address`, or `null` for none. */
function highestMatch(
  candidates: MatchablePermission[],
  address: string
): ComponentAccessLevel | null {
  const chain = addressChain(address)
  const tags = inheritedTags(address)

  let highest: ComponentAccessLevel | null = null
  for (const candidate of candidates) {
    const level = candidate.level
    if (level == null) {
      continue
    }

    const target = candidate.target ?? ''
    const matches =
      candidate.target_type === 'all' ||
      (candidate.target_type === 'component' && chain.includes(target)) ||
      (candidate.target_type === 'tag' && tags.has(target))

    if (matches && (highest == null || LEVEL_RANK[level] > LEVEL_RANK[highest])) {
      highest = level
    }
  }

  return highest
}

/** Describe where a component's effective level came from, for display beneath it. */
function accessSource(address: string, level: ComponentAccessLevel): string {
  const direct = highestMatch(permissions, address)
  if (direct != null && LEVEL_RANK[direct] === LEVEL_RANK[level]) {
    return 'Granted directly'
  }

  const groups = new Map<string, ComponentAccessLevel>()
  for (const permission of inheritedPermissions) {
    const matched = highestMatch([permission], address)
    if (matched == null) {
      continue
    }

    const existing = groups.get(permission.groupName)
    if (existing == null || LEVEL_RANK[matched] > LEVEL_RANK[existing]) {
      groups.set(permission.groupName, matched)
    }
  }

  for (const [name, matched] of groups) {
    if (LEVEL_RANK[matched] === LEVEL_RANK[level]) {
      return `From group "${name}"`
    }
  }

  return 'Default access level'
}

const effectiveAccess = $computed(() =>
  engine.components.all
    .map((component) => {
      const address = component.address.toString()
      const level = effectiveLevels.get(address) ?? null
      return {
        address,
        level,
        source: level == null ? null : accessSource(address, level),
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
          :to="`/groups/${permission.group_id}`"
        >
          <q-item-section>
            <q-item-label>
              {{ permissionTargetLabel(permission) }}
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
        <q-item v-for="entry in effectiveAccess" :key="entry.address">
          <q-item-section>
            <q-item-label>{{ entry.address }}</q-item-label>
            <q-item-label caption>{{ entry.source ?? 'No access' }}</q-item-label>
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
        <q-item v-if="effectiveAccess.length === 0">
          <q-item-section>
            <q-item-label class="text-grey-6">No components.</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card-section>
  </card-page-section>
</template>

<style lang="scss" module>
.caption {
  font-size: 12px;
  line-height: 1.4;
}

.addMenu {
  min-width: 220px;
}
</style>
