<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import { UserRole } from '@/api/users'
import CardPage from '@/components/CardPage.vue'
import { useDialogs } from '@/dialogs'
import { NotFoundError, guard } from '@/errors'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'
import { omit, upperFirst } from 'lodash'

const { id = null } = defineProps<{
  id?: string | null
}>()

const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()
const validate = useValidate()
const engine = useEngine()

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
      message: `Permanently delete the user "${user.username}"?`,
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

    const updated = await guard(engine.users.update(id, omit(data, ['password'])), [
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
</script>

<template>
  <card-page :title="getTitle()">
    <template #header-append>
      <q-space />
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
          <div class="col-8">
            <q-select
              v-model="form.data.role"
              dense
              hint="Set user permissions level."
              label="Role"
              :option-label="(role: UserRole) => upperFirst(role)"
              :options="['viewer', 'operator', 'admin']"
              options-dense
              outlined
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
                v-if="engine.auth.isAdmin && !isAccountPage"
                class="col"
                color="negative"
                :icon="icons.delete"
                label="Delete"
                @click="promptDelete"
              />
              <q-btn
                class="col"
                color="primary"
                :icon="icons.edit"
                label="Edit"
                @click="form.edit"
              />
            </template>
            <template v-else>
              <q-btn
                class="col"
                color="grey"
                :icon="icons.cancel"
                label="Cancel"
                @click="form.discard"
              />
              <q-btn
                class="col"
                color="primary"
                :disable="form.validation !== 'valid'"
                :icon="icons.submit"
                label="Update"
                @click="form.submit"
              />
            </template>
          </div>
          <template v-if="form.state === 'viewing' && (engine.auth.isAdmin || isAccountPage)">
            <div class="q-gutter-sm q-pt-sm row" spread>
              <q-btn
                color="warning"
                icon="password"
                label="Change Password"
                @click="promptChangePassword"
              />
              <q-btn
                v-if="isAccountPage"
                class="col"
                color="negative"
                icon="logout"
                label="Sign Out"
                @click="logout"
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
  </card-page>
</template>
