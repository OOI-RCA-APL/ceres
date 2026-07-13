<script lang="ts" setup>
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { omit } from 'lodash-es'
import { computed } from 'vue'

import { useEngine } from '@/api/engine'
import { Group } from '@/api/groups'
import { UserCreate } from '@/api/users'
import CardPage from '@/components/CardPage.vue'
import CardPageSection from '@/components/CardPageSection.vue'
import PermissionsSection from '@/components/PermissionsSection.vue'
import { useDialogs } from '@/dialogs'
import { NotFoundError, guard } from '@/errors'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'

const { id = null } = defineProps<{
  id?: string | null
}>()

const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()
const validate = useValidate()
const engine = useEngine()
const queryClient = useQueryClient()

const isAccountPage = $computed(() => id != null && id === engine.auth.user?.id)
const isShowingPassword = $ref(false)

const user = id != null ? await engine.users.get(id) : null
if (user == null && id != null) {
  throw new NotFoundError('user', `User ID "${id}" does not exist.`)
}

function getTitle() {
  if (isAccountPage) {
    return 'Account'
  } else if (user == null) {
    return 'Create User'
  } else {
    return form.data.username.trim() || user.username
  }
}

function promptChangePassword() {
  if (user == null) {
    return
  }

  dialogs.changePassword(user.id)
}

function promptDelete() {
  if (id == null || user == null) {
    return
  }

  dialogs
    .delete({
      title: 'Delete User',
      message: `Permanently delete user "${user.username}"?`,
    })
    .onOk(async () => {
      await engine.users.delete(id)
      notify.success(`User "${user.username}" deleted successfully.`)
      navigation.go('/users')
    })
}

async function logout() {
  await navigation.go('/')
  await engine.auth.logout()
  notify.success('You have signed out.', {
    icon: 'logout',
  })
}

const form = useForm({
  editing: user == null,
  data: <UserCreate>{
    username: '',
    email: '',
    password: '',
    disabled: false,
    admin: false,
  },
  validators: {
    username: validate.isUsername(
      'A username is required and can only contain letters, numbers or: ".-_".'
    ),
    email: validate.isEmail('A valid email address is required.'),
    password: user ? validate.accept() : validate.isNotEmpty('A password is required.'),
  },
  async onSubmit(data) {
    if (id == null) {
      // We're registering a new user.
      const created = await guard(engine.users.create(data), [
        {
          type: 'already-exists-error',
          do: () => notify.error(`User "${data.username}" already exists.`),
        },
      ])

      notify.success(`User "${created.username}" created successfully.`)
      navigation.go(`/users/${created.id}`)
      return
    }

    const update = engine.auth.isAdmin
      ? omit(data, ['password'])
      : omit(data, ['password', 'admin', 'disabled'])
    const updated = await guard(engine.users.update(id, update), [
      {
        type: 'already-exists-error',
        do: () => notify.error(`User "${data.username}" already exists.`),
      },
    ])

    if (isAccountPage) {
      notify.success('Account updated successfully.')
    } else {
      notify.success(`User "${updated.username}" updated successfully.`)
    }

    form.done(updated)

    // Refresh stored user data if the user changed their own info.
    if (isAccountPage) {
      void engine.auth.refresh()
    }
  },
})

form.load({
  ...user,
})

const membershipsQuery =
  id != null
    ? useQuery({
        queryKey: computed(() => ['user-group-memberships', id]),
        queryFn: () => engine.groups.getMembershipsForUser(id!),
      })
    : null

const allGroupsQuery =
  id != null
    ? useQuery({
        queryKey: ['all-groups'],
        queryFn: () => engine.groups.getAll(),
      })
    : null

const userGroupIds = $computed(
  () => new Set(membershipsQuery?.data.value?.map((membership) => membership.group_id) ?? [])
)

const userGroups = $computed(
  () => allGroupsQuery?.data.value?.filter((group: Group) => userGroupIds.has(group.id)) ?? []
)

const availableGroups = $computed(
  () => allGroupsQuery?.data.value?.filter((group: Group) => !userGroupIds.has(group.id)) ?? []
)

async function addToGroup(group: Group) {
  if (id == null) {
    return
  }

  await guard(engine.groups.addUserToGroup(id, group.id), () => {
    notify.error('Failed to add user to group.')
  })
  notify.success(`Added to "${group.name}".`)
  await membershipsQuery?.refetch()
  await queryClient.invalidateQueries({ queryKey: ['user-inherited-permissions', id] })
}

function promptRemoveFromGroup(group: Group) {
  if (id == null) {
    return
  }

  dialogs
    .show({
      title: 'Remove from Group',
      message: `Remove this user from "${group.name}"?`,
      ok: { label: 'Remove', color: 'negative', flat: true },
      cancel: { label: 'Cancel', flat: true, color: 'grey' },
    })
    .onOk(async () => {
      await guard(engine.groups.removeUserFromGroup(id!, group.id), () => {
        notify.error('Failed to remove user from group.')
      })
      notify.success(`Removed from "${group.name}".`)
      await membershipsQuery?.refetch()
      await queryClient.invalidateQueries({ queryKey: ['user-inherited-permissions', id] })
    })
}
</script>

<template>
  <card-page :title="getTitle()">
    <template #header-append>
      <q-space />
      <q-chip
        v-if="form.data.admin"
        class="q-px-sm"
        color="primary"
        dense
        :icon="icons.admin"
        size="13px"
        text-color="white"
      >
        Admin
        <q-tooltip class="bg-primary" :delay="250">
          <template v-if="isAccountPage">Your account has full administrative access.</template>
          <template v-else>This user's account has full administrative access.</template>
        </q-tooltip>
      </q-chip>
    </template>
    <q-form :ref="form.bind" @submit.prevent>
      <div class="q-pa-md">
        <q-input
          v-model="form.data.username"
          class="q-mb-sm"
          dense
          :hint="isAccountPage ? 'Your username, must be unique.' : 'The user\'s unique username.'"
          label="Username"
          lazy-rules
          outlined
          :readonly="form.readonly"
          :rules="[form.validators.username]"
          :spellcheck="false"
        >
          <template #prepend>
            <q-icon :name="icons.user" />
          </template>
        </q-input>
        <q-input
          v-if="user == null"
          v-model="form.data.password"
          class="q-mb-sm"
          dense
          hint="Pick an initial password they can use to sign in."
          label="Password"
          lazy-rules
          no-error-icon
          outlined
          :rules="[form.validators.password]"
          :type="isShowingPassword ? 'text' : 'password'"
        >
          <template #prepend>
            <q-icon name="password" />
          </template>
          <template #append>
            <q-icon
              class="cursor-pointer"
              :name="isShowingPassword ? 'visibility' : 'visibility_off'"
              @click="isShowingPassword = !isShowingPassword"
            />
          </template>
        </q-input>
        <q-input
          v-model="form.data.email"
          class="q-mb-sm"
          dense
          :hint="
            isAccountPage
              ? 'The email address you can be reached at.'
              : 'The email address this user can be reached at.'
          "
          label="Email"
          lazy-rules
          outlined
          :readonly="form.readonly"
          :rules="[form.validators.email]"
          :spellcheck="false"
          type="email"
        >
          <template #prepend>
            <q-icon name="mail" />
          </template>
        </q-input>
        <div v-if="engine.auth.isAdmin" class="q-col-gutter-md row">
          <div class="col-6">
            <q-toggle v-model="form.data.admin" :disable="form.readonly" label="Administrator">
              <q-tooltip class="bg-primary text-white">
                Grant full access to every component and setting.
              </q-tooltip>
            </q-toggle>
          </div>
          <div class="col-6">
            <q-toggle
              v-model="form.data.disabled"
              color="negative"
              :disable="form.readonly"
              label="Disabled"
            >
              <q-tooltip class="bg-negative text-white">
                Temporarily disable login access.
              </q-tooltip>
            </q-toggle>
          </div>
        </div>
      </div>
      <q-separator />
      <div class="q-pa-md">
        <template v-if="user">
          <div class="q-gutter-sm row">
            <template v-if="form.state === 'viewing'">
              <q-btn
                class="col"
                color="primary"
                :icon="icons.edit"
                label="Edit"
                unelevated
                @click="form.edit"
              />
            </template>
            <template v-else>
              <q-btn
                class="col"
                color="grey-8"
                :icon="icons.cancel"
                label="Cancel"
                unelevated
                @click="form.discard"
              />
              <q-btn
                class="col"
                color="primary"
                :disable="form.validation !== 'valid'"
                :icon="icons.submit"
                label="Update"
                unelevated
                @click="form.submit"
              />
            </template>
          </div>
          <template v-if="form.state === 'viewing' && (engine.auth.isAdmin || isAccountPage)">
            <div class="q-gutter-sm q-pt-sm row" spread>
              <q-btn
                class="col"
                color="warning"
                dense
                :icon="icons.password"
                label="Change Password"
                unelevated
                @click="promptChangePassword"
              />
              <q-btn
                v-if="isAccountPage"
                class="col"
                color="negative"
                dense
                :icon="icons.logout"
                label="Sign Out"
                unelevated
                @click="logout"
              />
              <q-btn
                v-if="engine.auth.isAdmin && !isAccountPage"
                class="col"
                color="negative"
                :icon="icons.delete"
                label="Delete"
                @click="promptDelete"
              />
            </div>
          </template>
        </template>
        <template v-else>
          <q-btn-group flat spread>
            <q-btn
              color="primary"
              :disable="form.validation !== 'valid'"
              :icon="icons.submit"
              label="Create"
              :loading="form.state === 'submitting'"
              @click="form.submit"
            />
          </q-btn-group>
        </template>
      </div>
    </q-form>

    <template v-if="user != null && engine.auth.isAdmin && form.state !== 'editing'" #sections>
      <card-page-section :title="`Groups (${userGroups.length})`">
        <q-card-section>
          <q-list bordered class="rounded-borders" dense separator>
            <q-item v-for="group in userGroups" :key="group.id" :to="`/groups/${group.id}`">
              <q-item-section>
                <q-item-label>{{ group.name }}</q-item-label>
                <q-item-label v-if="group.description" caption>
                  {{ group.description }}
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn
                  color="negative"
                  dense
                  flat
                  :icon="icons.delete"
                  round
                  size="sm"
                  @click.prevent="promptRemoveFromGroup(group)"
                />
              </q-item-section>
            </q-item>
            <q-item v-if="userGroups.length === 0">
              <q-item-section>
                <q-item-label class="text-grey-6"> No groups. </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <div class="justify-center q-mt-sm row">
            <q-btn color="primary" dense :icon="icons.add" round size="10px" unelevated>
              <q-tooltip class="bg-primary text-white">Add to Group</q-tooltip>
              <q-menu anchor="top middle" :offset="[0, 12]" self="bottom middle">
                <q-card bordered :class="$style.addMenu" flat>
                  <div class="q-pa-sm">
                    <q-card bordered flat>
                      <div
                        v-if="availableGroups.length === 0"
                        :class="[$style.emptyMessageText, 'q-pa-sm']"
                      >
                        No groups available.
                      </div>
                      <q-list v-else dense>
                        <q-item
                          v-for="group in availableGroups"
                          :key="group.id"
                          v-close-popup
                          clickable
                          @click="addToGroup(group)"
                        >
                          <q-item-section>
                            <q-item-label>{{ group.name }}</q-item-label>
                            <q-item-label v-if="group.description" caption>
                              {{ group.description }}
                            </q-item-label>
                          </q-item-section>
                        </q-item>
                      </q-list>
                    </q-card>
                  </div>
                </q-card>
              </q-menu>
            </q-btn>
          </div>
        </q-card-section>
      </card-page-section>
      <permissions-section v-if="id != null" :subject-id="id" subject-type="user" />
    </template>
  </card-page>
</template>

<style lang="scss" module>
.addMenu {
  min-width: 220px;
}

.emptyMessageText {
  text-align: center;
  font-size: 13px;
  opacity: 0.5;
}
</style>
