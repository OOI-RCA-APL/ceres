<script lang="ts" setup>
import { until } from '@vueuse/core'
import { compact, orderBy, upperFirst } from 'lodash-es'
import { useDialogPluginComponent } from 'quasar'
import { computed, watch, reactive, nextTick } from 'vue'

import { AuthStore } from '@/api/auth'
import { useQuery } from '@/api/client'
import { Engine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import { useForm } from '@/form'
import icons from '@/icons'
import { Navigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useTheme } from '@/theme'
import { useValidate } from '@/validate'
import {
  userCanManageWorkspace,
  WorkspaceData,
  WorkspaceAccessRestriction,
  WorkspaceAccessRestrictionModel,
  WorkspaceAccessRestrictionOf,
} from '@/workspace'

const { workspaceId, data, action, engine, auth, navigation } = $defineProps<
  (
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
  ) & {
    engine: Engine
    auth: AuthStore
    navigation: Navigation
  }
>()

defineEmits([...useDialogPluginComponent.emits])

const notify = useNotify()
const validate = useValidate()
const theme = useTheme()

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

let tab = $ref<'general' | 'members'>('general')

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

  return userCanManageWorkspace(auth.user, membership)
})

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

watch(
  () => form.data.general_managership,
  () => {
    if (
      WorkspaceAccessRestrictionOf[form.data.general_editorship] >
      WorkspaceAccessRestrictionOf[form.data.general_managership]
    ) {
      form.data.general_editorship = form.data.general_managership
    }
    if (
      WorkspaceAccessRestrictionOf[form.data.general_viewership] >
      WorkspaceAccessRestrictionOf[form.data.general_editorship]
    ) {
      form.data.general_viewership = form.data.general_editorship
    }
  }
)

watch(
  () => form.data.general_editorship,
  () => {
    if (
      WorkspaceAccessRestrictionOf[form.data.general_editorship] >
      WorkspaceAccessRestrictionOf[form.data.general_managership]
    ) {
      form.data.general_managership = form.data.general_editorship
    }

    if (
      WorkspaceAccessRestrictionOf[form.data.general_viewership] >
      WorkspaceAccessRestrictionOf[form.data.general_editorship]
    ) {
      form.data.general_viewership = form.data.general_editorship
    }
  }
)

watch(
  () => form.data.general_viewership,
  () => {
    if (
      WorkspaceAccessRestrictionOf[form.data.general_viewership] >
      WorkspaceAccessRestrictionOf[form.data.general_managership]
    ) {
      form.data.general_managership = form.data.general_viewership
    }

    if (
      WorkspaceAccessRestrictionOf[form.data.general_viewership] >
      WorkspaceAccessRestrictionOf[form.data.general_editorship]
    ) {
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

  return upperFirst(restriction)
}
</script>

<template>
  <q-dialog ref="dialogRef" :persistent="form.editable" @hide="onDialogHide">
    <q-card bordered class="q-dialog-plugin" :class="$style.card" flat>
      <div class="q-px-md row">
        <common-text class="q-mb-sm q-mt-sm" element="h2" variant="title1">
          {{ action === 'view' ? 'Workspace Settings' : 'Duplicate Workspace' }}
        </common-text>
        <q-space />
        <div class="items-center row">
          <q-btn flat :icon="icons.close" round size="10px" @click="onDialogCancel" />
        </div>
      </div>
      <q-spinner-orbit v-if="query.isLoading" />
      <template v-else>
        <template v-if="action === 'view'">
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
                <div class="q-pb-sm">
                  <common-text element="t3" variant="title3">General Permissions</common-text>
                </div>
                <div class="column q-col-gutter-y-sm q-mb-lg q-pt-none">
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
              <q-card bordered :class="['q-pa-none scroll', $style.userListContainer]" flat>
                <q-list dense>
                  <q-item v-for="membership in userMemberships" :key="membership.user.id">
                    <q-item-section>
                      <q-item-label>
                        {{ membership.user.username }}
                        <q-chip
                          v-if="membership.user.id === auth.user?.id"
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
                        <q-btn dense flat :icon="icons.more" round size="8px" />
                      </div>
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-card>
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

.userListContainer {
  max-height: 300px;
}
</style>
