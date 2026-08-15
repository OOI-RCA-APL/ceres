<script lang="ts" setup>
import { useQueryClient } from '@tanstack/vue-query'
import { omit } from 'lodash-es'
import { computed } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import type { Group } from '@/api/groups'
import type { UserCreate } from '@/api/users'
import { useDialogs } from '@/dialogs'
import { guard, NotFoundError } from '@/errors'
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

let isShowingPassword = $ref(false)

const user = id != null ? await engine.users.get(id) : null
if (user == null && id != null) {
  throw new NotFoundError('user', `User ID "${id}" does not exist.`)
}

const emptyUser: UserCreate = {
  username: '',
  email: '',
  password: '',
  disabled: false,
  admin: false,
}

const form = useForm({
  editing: user == null,
  data: emptyUser,
  validators: {
    username: validate.isUsername(
      'A username is required and can only contain letters, numbers or: ".-_".',
    ),
    email: validate.isEmail('A valid email address is required.'),
    password: user ? validate.accept() : validate.isNotEmpty('A password is required.'),
  },
  async onSubmit(data) {
    if (id == null) {
      const created = await guard(engine.users.create(data), {
        'already-exists-error': () => notify.error(`User "${data.username}" already exists.`),
      })

      notify.success(`User "${created.username}" created successfully.`)
      await navigation.go(`/users/${created.id}`)
      return
    }

    // Only an administrator may change what an account is allowed to be. The password has its own
    // dialog, so it never travels with the rest of the fields.
    const update = engine.auth.isAdmin
      ? omit(data, ['password'])
      : omit(data, ['password', 'admin', 'disabled'])
    const updated = await guard(engine.users.update(id, update), {
      'already-exists-error': () => notify.error(`User "${data.username}" already exists.`),
    })

    notify.success(
      isAccountPage
        ? 'Account updated successfully.'
        : `User "${updated.username}" updated successfully.`,
    )
    form.done(updated)

    if (isAccountPage) {
      void engine.auth.refresh()
    }
  },
})

form.load({ ...user })

const title = $computed(() => {
  if (isAccountPage) {
    return 'Account'
  }

  return user == null ? 'Create User' : form.data.username.trim() || user.username
})

const membershipsQuery =
  id != null
    ? useQuery({
        queryKey: computed(() => ['user-group-memberships', id]),
        queryFn: () => engine.groups.getMembershipsForUser(id),
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
  () => new Set(membershipsQuery?.data.value?.map((membership) => membership.group_id) ?? []),
)

const userGroups = $computed(
  () => allGroupsQuery?.data.value?.filter((group) => userGroupIds.has(group.id)) ?? [],
)

let isAddingToGroup = $ref(false)

/** Group membership decides what a user inherits, so the permissions section has to be rebuilt
alongside the membership list. */
async function refreshMemberships() {
  await membershipsQuery?.refetch()
  await queryClient.invalidateQueries({ queryKey: ['user-inherited-permissions', id] })
}

async function addToGroup(group: Group) {
  if (id == null) {
    return
  }

  isAddingToGroup = false
  await guard(engine.groups.addUserToGroup(id, group.id), () => {
    notify.error('Failed to add user to group.')
  })
  notify.success(`Added to "${group.name}".`)
  await refreshMemberships()
}

function promptRemoveFromGroup(group: Group) {
  if (id == null) {
    return
  }

  dialogs
    .show({
      title: 'Remove from Group',
      message: `Remove this user from "${group.name}"?`,
      okLabel: 'Remove',
      okColor: 'error',
    })
    .onOk(async () => {
      await guard(engine.groups.removeUserFromGroup(id, group.id), () => {
        notify.error('Failed to remove user from group.')
      })
      notify.success(`Removed from "${group.name}".`)
      await refreshMemberships()
    })
}

function promptChangePassword() {
  if (user != null) {
    dialogs.changePassword(user.id)
  }
}

function promptDelete() {
  if (id == null || user == null) {
    return
  }

  dialogs.delete({ message: `Permanently delete user "${user.username}"?` }).onOk(async () => {
    await engine.users.delete(id)
    notify.success(`User "${user.username}" deleted successfully.`)
    await navigation.go('/users')
  })
}

async function logout() {
  await navigation.go('/')
  await engine.auth.logout()
  notify.success('You have signed out.', { icon: icons.logout })
}

const rowClass = 'flex items-center gap-2 px-3 py-1.5'
</script>

<template>
  <c-card-page :title>
    <template #header-append>
      <c-tooltip
        :text="
          isAccountPage
            ? 'Your account has full administrative access.'
            : `This user's account has full administrative access.`
        "
      >
        <c-badge v-if="form.data.admin" color="primary" :icon="icons.admin" size="sm">
          Admin
        </c-badge>
      </c-tooltip>
    </template>

    <form @submit.prevent="form.submit()">
      <div class="flex flex-col gap-3 p-4">
        <c-form-field
          :description="
            isAccountPage ? 'Your username, must be unique.' : `The user's unique username.`
          "
          label="Username"
        >
          <c-input
            v-model="form.data.username"
            class="w-full"
            :disabled="form.readonly"
            :icon="icons.user"
            :spellcheck="false"
          />
        </c-form-field>
        <c-form-field
          v-if="user == null"
          description="Pick an initial password they can use to sign in."
          label="Password"
        >
          <c-input
            v-model="form.data.password"
            class="w-full"
            :icon="icons.password"
            :type="isShowingPassword ? 'text' : 'password'"
          >
            <template #trailing>
              <c-button
                color="neutral"
                :icon="isShowingPassword ? icons.view : icons.locked"
                size="xs"
                variant="link"
                @click="isShowingPassword = !isShowingPassword"
              />
            </template>
          </c-input>
        </c-form-field>
        <c-form-field
          :description="
            isAccountPage
              ? 'The email address you can be reached at.'
              : 'The email address this user can be reached at.'
          "
          label="Email"
        >
          <c-input
            v-model="form.data.email"
            class="w-full"
            :disabled="form.readonly"
            :icon="icons.email"
            :spellcheck="false"
            type="email"
          />
        </c-form-field>
        <div v-if="engine.auth.isAdmin" class="flex gap-4">
          <c-tooltip text="Grant full access to every component and setting.">
            <c-switch v-model="form.data.admin" :disabled="form.readonly" label="Administrator" />
          </c-tooltip>
          <c-tooltip text="Temporarily disable login access.">
            <c-switch
              v-model="form.data.disabled"
              color="error"
              :disabled="form.readonly"
              label="Disabled"
            />
          </c-tooltip>
        </div>
      </div>
      <c-separator />
      <div class="p-4">
        <template v-if="user">
          <div class="flex gap-2">
            <c-button
              v-if="form.state === 'viewing'"
              block
              class="flex-1"
              :icon="icons.edit"
              label="Edit"
              @click="form.edit()"
            />
            <template v-else>
              <c-button
                block
                class="flex-1"
                color="neutral"
                :icon="icons.cancel"
                label="Cancel"
                @click="form.discard()"
              />
              <c-button
                block
                class="flex-1"
                :disabled="form.validation !== 'valid'"
                :icon="icons.submit"
                label="Update"
                @click="form.submit()"
              />
            </template>
          </div>
          <div
            v-if="form.state === 'viewing' && (engine.auth.isAdmin || isAccountPage)"
            class="mt-2 flex gap-2"
          >
            <c-button
              block
              class="flex-1"
              color="warning"
              :icon="icons.password"
              label="Change Password"
              @click="promptChangePassword"
            />
            <c-button
              v-if="isAccountPage"
              block
              class="flex-1"
              color="error"
              :icon="icons.logout"
              label="Sign Out"
              @click="logout"
            />
            <c-button
              v-if="engine.auth.isAdmin && !isAccountPage"
              block
              class="flex-1"
              color="error"
              :icon="icons.delete"
              label="Delete"
              @click="promptDelete"
            />
          </div>
        </template>
        <c-button
          v-else
          block
          :disabled="form.validation !== 'valid'"
          :icon="icons.submit"
          label="Create"
          :loading="form.state === 'submitting'"
          @click="form.submit()"
        />
      </div>
    </form>

    <template
      v-if="id != null && user != null && engine.auth.isAdmin && form.state !== 'editing'"
      #sections
    >
      <c-card-page-section :title="`Groups (${userGroups.length})`">
        <div class="p-4">
          <div class="divide-default divide-y rounded-md border border-default">
            <nuxt-link
              v-for="group in userGroups"
              :key="group.id"
              :class="[rowClass, 'hover:bg-elevated']"
              :to="`/groups/${group.id}`"
            >
              <span class="min-w-0 grow">
                <c-text class="block truncate" variant="body2">{{ group.name }}</c-text>
                <c-text v-if="group.description" class="block truncate" variant="description">
                  {{ group.description }}
                </c-text>
              </span>
              <c-button
                color="error"
                :icon="icons.delete"
                size="xs"
                variant="ghost"
                @click.prevent="promptRemoveFromGroup(group)"
              />
            </nuxt-link>
            <div v-if="userGroups.length === 0" :class="rowClass">
              <c-text class="text-muted block" variant="body2">No groups.</c-text>
            </div>
          </div>
          <div class="mt-2 flex justify-center">
            <c-popover
              v-model:open="isAddingToGroup"
              :content="{ side: 'top' }"
              :ui="{ content: 'w-[220px]' }"
            >
              <c-tooltip text="Add to Group">
                <c-button :icon="icons.add" size="xs" />
              </c-tooltip>
              <template #content>
                <c-group-chooser
                  empty="No groups available."
                  :omit="(group: Group) => userGroupIds.has(group.id)"
                  @select="addToGroup"
                />
              </template>
            </c-popover>
          </div>
        </div>
      </c-card-page-section>
      <c-permissions-section :subject-id="id" subject-type="user" />
    </template>
  </c-card-page>
</template>
