<script lang="ts" setup>
import { until } from '@vueuse/core'
import { compact, orderBy, upperFirst } from 'lodash-es'
import { useDialogPluginComponent } from 'quasar'
import { reactive, computed, watch, nextTick } from 'vue'

import { useAccess } from '@/api/access'
import { useAuth } from '@/api/auth'
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { User } from '@/api/users'
import CommonText from '@/components/CommonText.vue'
import UserChooser from '@/components/UserChooser.vue'
import { useDialogs } from '@/dialogs'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useTheme } from '@/theme'
import { useValidate } from '@/validate'
import {
  userCanManageWorkspace,
  WorkspaceAccessRestriction,
  WorkspaceAccessRestrictionModel,
  WorkspaceData,
  WorkspaceMembership,
  WorkspaceMembershipRole,
  WorkspaceMembershipRoleModel,
  WorkspaceMembershipRoleOf,
} from '@/workspace'

const { workspaceId, data, action } = defineProps<
  | {
      workspaceId: string
      action: 'view'
      data?: null
    }
  | {
      workspaceId: string
      action: 'duplicate'
      data?: WorkspaceData
    }
>()

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const engine = useEngine()
const navigation = useNavigation()
const notify = useNotify()
const theme = useTheme()
const validate = useValidate()

let tab = $ref<'general' | 'members'>('general')

let addingMember = $ref<User | null>(null)
let addingMemberRole = $ref<WorkspaceMembershipRole | null>(null)

const key = Math.random()
const query = reactive(
  useQuery({
    queryKey: computed(() => ['workspace-dialog', workspaceId, auth.user?.id, key]),
    queryFn: async () => {
      await auth.refresh()
      let [workspace, membership, memberships, users] = await Promise.all([
        engine.workspaces.get(workspaceId),
        engine.workspaces.getMembership(workspaceId),
        engine.workspaces.getMembershipsInWorkspace(workspaceId),
        engine.users.getAll({
          has_workspace_membership: workspaceId,
        }),
      ])

      users = orderBy(users, (current) => (current.id === auth.user?.id ? 0 : 1))

      return { workspace, membership, memberships, users }
    },
  })
)

const workspace = $computed(() => query.data?.workspace ?? null)
const membership = $computed(() => query.data?.membership ?? null)
const memberships = $computed(() => query.data?.memberships ?? [])
const users = $computed(() => query.data?.users ?? [])
const canManage = $computed(() => {
  if (action === 'duplicate') {
    return true
  }
  if (workspace == null) {
    return false
  }

  // A scoped workspace has no memberships, its capabilities come from the scope component.
  if (workspace.scope != null) {
    return access.canManage(workspace.scope.toString())
  }

  return userCanManageWorkspace(auth.user, membership)
})

// Memberships do not apply to a scoped workspace, so its members tab has nothing to show.
const hasMembers = $computed(() => workspace?.scope == null)

const userMemberships = $computed(() =>
  compact(
    users.map((user) => {
      const membership = memberships.find((current) => current.user_id === user.id)
      if (membership == null) {
        return null
      }

      return { ...membership, user }
    })
  )
)

const memberIds = $computed(() => new Set(userMemberships.map((membership) => membership.user.id)))

type UserWorkspaceMembership = WorkspaceMembership & {
  user: User
}

const form = useForm({
  editing: action === 'duplicate',
  data: {
    name: 'New Workspace',
    general_viewership: 'private' as WorkspaceAccessRestriction,
    general_editorship: 'private' as WorkspaceAccessRestriction,
    general_managership: 'private' as WorkspaceAccessRestriction,
  },
  validators: {
    name: validate.isNotBlank(),
  },
  onSubmit: async (values) => {
    if (action === 'view') {
      await engine.workspaces.update(workspaceId, values)
      notify.success('Workspace settings updated successfully.')
    } else if (action === 'duplicate' && workspaceId) {
      const copy = await engine.workspaces.create({
        ...values,
        data: data ?? workspace?.data ?? {},
      })
      notify.success('Workspace duplicated successfully.')
      navigation.go(`/workspaces/${copy.id}`)
    }

    onDialogOK()
  },
})

// With only 'anyone' and 'private' as restriction levels, a restriction is stricter than
// another exactly when it is 'private' and the other is 'anyone'.
function isStricter(restriction: WorkspaceAccessRestriction, other: WorkspaceAccessRestriction) {
  return restriction === 'private' && other === 'anyone'
}

watch(
  () => form.data.general_managership,
  () => {
    if (isStricter(form.data.general_editorship, form.data.general_managership)) {
      form.data.general_editorship = form.data.general_managership
    }
    if (isStricter(form.data.general_viewership, form.data.general_editorship)) {
      form.data.general_viewership = form.data.general_editorship
    }
  }
)

watch(
  () => form.data.general_editorship,
  () => {
    if (isStricter(form.data.general_editorship, form.data.general_managership)) {
      form.data.general_managership = form.data.general_editorship
    }

    if (isStricter(form.data.general_viewership, form.data.general_editorship)) {
      form.data.general_viewership = form.data.general_editorship
    }
  }
)

watch(
  () => form.data.general_viewership,
  () => {
    if (isStricter(form.data.general_viewership, form.data.general_managership)) {
      form.data.general_managership = form.data.general_viewership
    }

    if (isStricter(form.data.general_viewership, form.data.general_editorship)) {
      form.data.general_editorship = form.data.general_viewership
    }
  }
)

nextTick(async () => {
  await until(() => query.isFetched).toBe(true)
  if (workspace != null) {
    form.load(workspace)
    if (action === 'duplicate') {
      form.data.name = `${workspace.name} (Copy)`
    }
  }
})

function getRestrictionLabel(restriction: WorkspaceAccessRestriction) {
  if (restriction === 'private') {
    return 'Private (Members Only)'
  }

  return 'Anyone'
}

async function addMember(user: User, role: WorkspaceMembershipRole) {
  try {
    await engine.workspaces.createMembership(user.id, workspaceId, role)
    notify.success(`User "${user.username}" added to workspace successfully.`)
  } finally {
    query.refetch()
    addingMember = null
    addingMemberRole = null
  }
}

function promptRemoveMember(membership: UserWorkspaceMembership) {
  if (workspace == null) {
    return
  }

  dialogs
    .confirm({
      title: 'Remove Member',
      message: `Remove user "${membership.user.username}" from this workspace?`,
      ok: {
        label: 'Yes',
        color: 'negative',
      },
    })
    .onOk(async () => {
      await engine.workspaces.deleteMembership(membership.user_id, workspaceId)

      notify.success(`User "${membership.user.username}" removed from workspace successfully.`)
      query.refetch()
    })
}

function promptChangeRole(membership: UserWorkspaceMembership, role: WorkspaceMembershipRole) {
  if (membership == null || workspace == null) {
    return
  }

  const isDemotion = WorkspaceMembershipRoleOf[role] < WorkspaceMembershipRoleOf[membership.role]
  const verb = isDemotion ? 'Demote' : 'Promote'

  dialogs
    .confirm({
      title: 'Change Workspace Role',
      message: `${verb} "${membership.user.username}" from ${membership.role} to ${role}?`,
      ok: {
        label: 'Yes',
        color: 'negative',
      },
    })
    .onOk(async () => {
      if (membership == null || workspace == null) {
        return
      }

      await engine.workspaces.updateMembership(membership.user_id, workspace.id, {
        role,
      })

      notify.success(`Workspace role of "${membership.user.username}" changed successfully.`)
      query.refetch()
    })
}
</script>

<template>
  <q-dialog ref="dialogRef" :persistent="form.editable" @hide="onDialogHide">
    <q-card v-if="auth.user != null" bordered class="q-dialog-plugin" :class="$style.card" flat>
      <div class="q-px-md row">
        <common-text class="q-mb-sm q-mt-sm" element="h2" variant="title1">
          {{ action === 'view' ? 'Workspace Settings' : 'Duplicate Workspace' }}
        </common-text>
        <q-space />
        <div class="items-center row">
          <q-btn flat :icon="icons.close" round size="10px" @click="onDialogCancel" />
        </div>
      </div>
      <div v-if="query.isLoading" class="justify-center q-pa-md row">
        <q-spinner-orbit color="primary" size="25px" />
      </div>
      <template v-else>
        <template v-if="action === 'view' && hasMembers">
          <q-separator />
          <q-tabs
            v-model="tab"
            active-color="primary"
            dense
            inactive-color="grey"
            indicator-color="transparent"
            no-caps
          >
            <q-tab :class="$style.tab" label="General" name="general" />
            <q-separator vertical />

            <q-tab
              :class="$style.tab"
              :content-class="$style.membershipsTabContent"
              label="Members"
              name="members"
            >
              <q-badge
                :class="[$style.membershipsCountBadge, 'q-ml-sm']"
                :color="tab === 'members' ? 'primary' : theme.darklight('grey-1', () => 'black')"
                rounded
                :text-color="tab === 'members' ? 'white' : theme.darklight('black', 'white')"
              >
                {{ userMemberships.length }}
              </q-badge>
            </q-tab>
          </q-tabs>
          <div class="row">
            <q-separator :class="[tab === 'general' && $style.invisible, 'col']" />
            <q-separator :class="[tab === 'members' && $style.invisible, 'col']" />
          </div>
        </template>
        <q-separator v-else-if="action === 'view'" />
        <q-tab-panels v-model="tab">
          <q-tab-panel class="q-px-none" name="general">
            <q-form :ref="form.bind" @submit="form.submit">
              <div v-if="query.error" class="q-pt-none q-px-md">
                <common-text element="p" variant="body1">
                  An error occurred while loading the workspace. {{ query.error }}
                </common-text>
              </div>
              <div v-else class="q-pt-none q-px-md">
                <q-input
                  v-model="form.data.name"
                  autofocus
                  class="q-mb-md"
                  color="primary"
                  dense
                  label="Workspace Name"
                  lazy-rules
                  no-error-icon
                  outlined
                  :readonly="form.readonly"
                />
                <div v-if="!hasMembers" class="q-mb-lg text-grey-6">
                  Access to this workspace follows the
                  <span class="monospace-xs">{{ workspace?.scope }}</span> component, so anyone who
                  can view that component can see it, and anyone who can manage it can edit it.
                </div>
                <div v-if="hasMembers" class="q-pb-sm">
                  <common-text element="t3" variant="title3">General Permissions</common-text>
                </div>
                <div v-if="hasMembers" class="column q-col-gutter-y-sm q-mb-lg q-pt-none">
                  <q-select
                    v-model="form.data.general_viewership"
                    color="primary"
                    dense
                    :hint="
                      'Global subset of users who can discover and join this workspace as a ' +
                      'viewer.'
                    "
                    label="View Access"
                    lazy-rules
                    no-error-icon
                    :option-label="getRestrictionLabel"
                    :options="WorkspaceAccessRestrictionModel.options"
                    options-dense
                    outlined
                    :readonly="form.readonly"
                  />
                  <q-select
                    v-model="form.data.general_editorship"
                    color="primary"
                    dense
                    :hint="
                      'Global subset of users who can join this workspace as an editor, able to ' +
                      'modify its shared contents.'
                    "
                    label="Edit Access"
                    lazy-rules
                    no-error-icon
                    :option-label="getRestrictionLabel"
                    :options="WorkspaceAccessRestrictionModel.options"
                    options-dense
                    outlined
                    :readonly="form.readonly"
                  />
                  <q-select
                    v-model="form.data.general_managership"
                    color="primary"
                    dense
                    :hint="
                      'Global subset of users who can join this workspace as a manager, able to ' +
                      'modify its name, settings, members, and contents, in addition to being ' +
                      'able to delete it entirely.'
                    "
                    label="Management Access"
                    lazy-rules
                    no-error-icon
                    :option-label="getRestrictionLabel"
                    :options="WorkspaceAccessRestrictionModel.options"
                    options-dense
                    outlined
                    :readonly="form.readonly"
                  />
                </div>
              </div>
            </q-form>
            <div v-if="canManage" class="q-col-gutter-x-sm q-pt-sm q-px-md row">
              <div v-if="action === 'view' && form.readonly" class="col">
                <q-btn
                  class="full-width"
                  color="primary"
                  :icon="icons.edit"
                  label="Edit"
                  unelevated
                  @click="form.edit()"
                />
              </div>
              <div v-if="action === 'view' && form.editable" class="col">
                <q-btn
                  class="full-width"
                  color="grey-8"
                  :icon="icons.cancel"
                  label="Cancel"
                  unelevated
                  @click="form.discard()"
                />
              </div>
              <div v-if="form.editable" class="col">
                <q-btn
                  class="full-width"
                  color="primary"
                  :disable="form.validation !== 'valid'"
                  :icon="icons.confirm"
                  :label="action !== 'view' ? upperFirst(action) : 'Save'"
                  :loading="form.state === 'submitting'"
                  type="submit"
                  unelevated
                  @click="form.submit()"
                />
              </div>
            </div>
          </q-tab-panel>
          <q-tab-panel name="members">
            <div class="column q-col-gutter-y-sm q-pt-xs">
              <div v-if="userMemberships.length === 0" class="q-pa-sm text-center">
                This workspace has no members.
              </div>
              <q-card
                v-else
                bordered
                :class="['q-pa-none q-mb-xs scroll', $style.memberListContainer]"
                flat
              >
                <q-list dense>
                  <q-item v-for="membership in userMemberships" :key="membership.user.id">
                    <q-item-section>
                      <q-item-label>
                        {{ membership.user.username }}
                        <q-chip
                          v-if="membership.user.id === auth.user.id"
                          class="q-ml-sm"
                          color="primary"
                          dense
                          flat
                          outline
                          size="10px"
                        >
                          You
                        </q-chip>
                      </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                      <div class="items-center q-gutter-x-sm row">
                        <q-chip
                          class="q-px-sm"
                          color="primary"
                          dense
                          :icon="icons[membership.role]"
                          size="10px"
                          text-color="white"
                        >
                          {{ upperFirst(membership.role) }}
                        </q-chip>
                        <q-btn
                          dense
                          :disable="!canManage || membership.user.id === auth.user.id"
                          flat
                          :icon="icons.more"
                          round
                          size="8px"
                        >
                          <q-menu anchor="top right" :offset="[8, 7]" self="top left">
                            <q-card bordered flat>
                              <q-list dense>
                                <q-item clickable>
                                  <q-item-section avatar>
                                    <q-icon :name="icons.changeRole" />
                                  </q-item-section>
                                  <q-item-section>
                                    <q-item-label>Change Role</q-item-label>
                                  </q-item-section>
                                  <q-item-section side>
                                    <q-icon :name="icons.menuRight" size="16px" />
                                  </q-item-section>
                                  <q-menu
                                    v-if="membership.user.id !== auth.user.id"
                                    anchor="top right"
                                    :offset="[8, 1]"
                                    self="top left"
                                  >
                                    <q-card bordered flat>
                                      <q-list dense>
                                        <q-item
                                          v-for="role in WorkspaceMembershipRoleModel.options"
                                          :key="role"
                                          v-close-popup
                                          clickable
                                          :disable="membership.role === role"
                                          @click="promptChangeRole(membership, role)"
                                        >
                                          <q-item-section avatar>
                                            <q-icon :name="icons[role]" />
                                          </q-item-section>
                                          <q-item-section>
                                            <q-item-label>To {{ upperFirst(role) }}</q-item-label>
                                          </q-item-section>
                                        </q-item>
                                      </q-list>
                                    </q-card>
                                  </q-menu>
                                </q-item>
                                <q-item
                                  v-close-popup
                                  clickable
                                  @click="promptRemoveMember(membership)"
                                >
                                  <q-item-section avatar>
                                    <q-icon :name="icons.removeMember" />
                                  </q-item-section>
                                  <q-item-section>
                                    <q-item-label>Remove</q-item-label>
                                  </q-item-section>
                                </q-item>
                              </q-list>
                            </q-card>
                          </q-menu>
                        </q-btn>
                      </div>
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-card>
              <div v-if="canManage" class="justify-center row">
                <q-btn color="primary" dense :icon="icons.add" round size="10px" unelevated>
                  <q-tooltip class="bg-primary text-white">Add Member</q-tooltip>
                  <q-menu
                    anchor="top middle"
                    :offset="[0, 12]"
                    self="bottom middle"
                    @hide="addingMember = null"
                  >
                    <q-card bordered :class="$style.addMemberMenu" flat>
                      <user-chooser
                        v-if="addingMember == null"
                        :omit="(user) => user.id === auth.user?.id || memberIds.has(user.id)"
                        @select="(user) => (addingMember = user)"
                      />
                      <div v-else class="column q-col-gutter-sm q-pa-sm">
                        <div>
                          <q-card bordered class="q-py-xs" flat>
                            <q-item dense>
                              <q-item-section>
                                <q-item-label>{{ addingMember.username }}</q-item-label>
                                <q-item-label caption>{{ addingMember.email }}</q-item-label>
                              </q-item-section>
                            </q-item>
                          </q-card>
                        </div>
                        <q-select
                          v-model="addingMemberRole"
                          autofocus
                          dense
                          label="Workspace Role"
                          :option-label="upperFirst"
                          :options="WorkspaceMembershipRoleModel.options"
                          options-dense
                          outlined
                        />
                        <div>
                          <q-btn
                            v-close-popup
                            class="full-width"
                            color="primary"
                            dense
                            :disable="addingMemberRole == null"
                            label="Add"
                            @click="
                              () => {
                                if (addingMember != null && addingMemberRole != null) {
                                  addMember(addingMember, addingMemberRole)
                                }
                              }
                            "
                          />
                        </div>
                      </div>
                    </q-card>
                  </q-menu>
                </q-btn>
              </div>
            </div>
          </q-tab-panel>
        </q-tab-panels>
      </template>
    </q-card>
  </q-dialog>
</template>

<style lang="scss" module>
.card {
  max-width: 560px;
  width: 560px;
}

.invisible {
  opacity: 0;
}

.tab {
  margin-top: -1px;
  flex: 1 !important;
}

.membershipsTabContent {
  flex-direction: row !important;
}

.membershipsCountBadge {
  opacity: 0.85;
}

.memberListContainer {
  max-height: 300px;
}

.addMemberMenu {
  min-width: 220px;
}
</style>
