<script lang="ts" setup>
import { UserRole } from '@/api/models'
import { createUser, deleteUser, getUser, isError, updateUser } from '@/api/operations'
import { useAuth } from '@/auth'
import CardPage from '@/components/CardPage.vue'
import { useDialogs } from '@/dialogs'
import { NotFoundError } from '@/errors'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'
import { omit, upperFirst } from 'lodash'

const { id = null } = defineProps<{
  id?: string | null
}>()

const auth = useAuth()
const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()
const validate = useValidate()

const isAccountPage = $computed(() => id != null && id === auth.user?.id)
const isShowingPassword = $ref(false)

const user = id != null ? await getUser(id) : null
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
      message: `Permanently delete the user "${user.username}"?`,
    })
    .onOk(async () => {
      if (id == null) {
        return
      }

      const result = await deleteUser(id)
      if (isError(result)) {
        notify.error(`Failed to delete user. (${result.type})`)
      } else {
        notify.success('User deleted successfully.')
        navigation.go('/users')
      }
    })
}

async function logout() {
  await navigation.go('/')
  await auth.logout()
  notify.success('You have signed out.', {
    icon: 'logout',
  })
}

const form = useForm({
  editing: user == null,
  data: {
    username: '',
    email: '',
    password: '',
    disabled: false,
    role: 'operator' as UserRole,
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
      const result = await createUser(data)
      if (isError(result)) {
        if (result.type === 'already-exists-error') {
          notify.error(`User "${data.username}" already exists.`)
        } else {
          notify.error(`Failed to create user. (${result.type})`)
        }
        return
      }

      notify.success('User created successfully.')
      navigation.go(`/users/${result.id}`)
      return
    }

    const result = await updateUser(id, omit(data, ['password']))
    if (isError(result)) {
      if (result.type === 'already-exists-error') {
        notify.error(`User "${data.username}" already exists.`)
      } else {
        notify.error(`Failed to update user. (${result.type})`)
      }
      return
    }

    if (isAccountPage) {
      notify.success('Account updated successfully.')
    } else {
      notify.success('User updated successfully.')
    }

    form.done(result)

    // Refresh stored user data if the user changed their own info.
    if (isAccountPage) {
      void auth.refresh()
    }
  },
})

form.load({
  ...user,
})
</script>

<template>
  <card-page :title="getTitle()">
    <template #header-append>
      <q-space />
      <q-chip :color="$q.dark.isActive ? 'grey-7' : 'grey-3'" :label="upperFirst(form.data.role)" />
    </template>
    <q-form :ref="form.bind" @submit.prevent>
      <div class="q-pa-md">
        <q-input
          v-model="form.data.username"
          class="q-mb-sm"
          dense
          filled
          :hint="isAccountPage ? 'Your username, must be unique.' : 'The user\'s unique username.'"
          label="Username"
          lazy-rules
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
          filled
          hint="Pick an initial password they can use to sign in."
          label="Password"
          lazy-rules
          no-error-icon
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
          filled
          :hint="
            isAccountPage
              ? 'The email address you can be reached at.'
              : 'The email address this user can be reached at.'
          "
          label="Email"
          lazy-rules
          :readonly="form.readonly"
          :rules="[form.validators.email]"
          :spellcheck="false"
          type="email"
        >
          <template #prepend>
            <q-icon name="mail" />
          </template>
        </q-input>
        <div v-if="auth.isAdmin && !isAccountPage" class="q-col-gutter-md row">
          <div class="col-8">
            <q-select
              v-model="form.data.role"
              dense
              filled
              hint="Set the user's permissions."
              label="Role"
              :option-label="(role: UserRole) => upperFirst(role)"
              :options="['viewer', 'operator', 'admin']"
              options-dense
              :readonly="form.readonly"
            />
          </div>
          <div class="col-4">
            <q-toggle
              v-model="form.data.disabled"
              color="negative"
              :disable="form.readonly"
              label="Disabled"
            >
              <q-tooltip class="bg-negative text-white">
                Temporarily disable login access for this user.
              </q-tooltip>
            </q-toggle>
          </div>
        </div>
      </div>
      <q-separator />
      <div class="q-pa-md">
        <template v-if="user">
          <q-btn-group flat spread>
            <template v-if="form.state === 'viewing'">
              <q-btn
                v-if="auth.isAdmin && !isAccountPage"
                color="negative"
                flat
                :icon="icons.delete"
                label="Delete"
                @click="promptDelete"
              />
              <q-btn color="primary" flat :icon="icons.edit" label="Edit" @click="form.edit" />
            </template>
            <template v-else>
              <q-btn color="grey" flat :icon="icons.cancel" label="Cancel" @click="form.discard" />
              <q-btn
                color="primary"
                :disable="form.validation !== 'valid'"
                flat
                :icon="icons.submit"
                label="Update"
                @click="form.submit"
              />
            </template>
          </q-btn-group>
          <template v-if="form.state === 'viewing' && (auth.isAdmin || isAccountPage)">
            <q-btn-group class="q-mt-xs" flat spread>
              <q-btn
                color="primary"
                flat
                icon="password"
                label="Change Password"
                @click="promptChangePassword"
              />
              <q-btn
                v-if="isAccountPage"
                class="col"
                color="negative"
                flat
                icon="logout"
                label="Sign Out"
                @click="logout"
              />
            </q-btn-group>
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
  </card-page>
</template>
