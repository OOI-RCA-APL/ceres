<script lang="ts" setup>
import { UserRole } from '@/api/models'
import { useAuth } from '@/auth'
import { useDialogs } from '@/dialogs'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import CardPage from '@/page-layouts/CardPage.vue'
import { useStore } from '@/store'
import { useValidate } from '@/validate'
import _, { upperFirst } from 'lodash'
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    id?: string | null
  }>(),
  {
    id: null,
  }
)

const auth = useAuth()
const dialogs = useDialogs()
const navigation = useNavigation()
const validate = useValidate()
const store = useStore()

const id = $computed(() => props.id)
const isAccountPage = $computed(() => id === auth.user?.id)
const isShowingPassword = ref(false)
const user = function getTitle() {
  if (isAccountPage) {
    return 'Account'
  } else if (auth.user == null) {
    return 'Create User'
  } else {
    return form.data.username.trim() || auth.user.username
  }
}

function promptChangePassword() {
  if (auth.user == null) {
    return
  }

  dialogs.changePassword(auth.user.id)
}

function promptDelete() {
  if (auth.user == null) {
    return
  }

  async function execute() {
    if (auth.user == null) {
      return
    }

    guard(
      await mutations.delete.executeMutation({
        id: user.id,
      }),
      [
        {
          code: 'constraint-violation',
          text: 'notes',
          do: () => notify.error('Cannot delete a user with associated operator log entries.'),
        },
      ],
      async () => {
        notify.success('User deleted successfully.')
        await navigation.go('/users')
      }
    )
  }

  dialogs
    .delete({
      message: `Permanently delete the user "${auth.user?.username}"?`,
    })
    .onOk(() => void execute())
}

async function logout() {
  await Promise.all([navigation.go('/'), auth.logout()])
  notify.success('You have signed out.', {
    icon: 'logout',
  })
}

const form = useForm({
  editing: user == null,
  data: {
    id,
    username: '',
    email: '',
    password: '',
    disabled: false,
    role: 'operator',
  },
  validators: {
    username: validate.isUsername(
      'A username is required and can only contain letters, numbers or: ".-_".'
    ),
    email: validate.isEmail('A valid email address is required.'),
    password: auth.user ? validate.accept() : validate.isNotEmpty('A password is required.'),
  },
  async onSubmit(data) {
    if (auth.user == null) {
      // We're registering a new user.
      return
    }

    guard(
      store.user.role === 'admin'
        ? await mutations.adminUpdate.executeMutation(_.omit(data, ['password']))
        : await mutations.operatorUpdate.executeMutation(
            _.omit(data, ['password', 'roleCode', 'isDisabled'])
          ),
      [
        {
          code: 'constraint-violation',
          text: 'username',
          do: () => notify.error('That username is taken.'),
        },
      ],
      (result) => {
        if (isAccountPage) {
          notify.success('Account updated successfully.')
        } else {
          notify.success('User updated successfully.')
        }

        form.done(result.user as any)

        // Refresh stored user data if the user changed their own info.
        if (isAccountPage) {
          void store.refresh()
        }
      }
    )
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
      <q-chip :label="upperFirst(form.data.role)" />
    </template>
    <q-card-section>
      <q-form :ref="form.bind" @submit.prevent>
        <q-input
          v-model="form.data.username"
          class="q-mb-md"
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
          v-model="form.data.email"
          class="q-mb-md"
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
        <q-input
          v-if="user == null"
          v-model="form.data.password"
          class="q-mb-md"
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
        <div v-if="auth.isAdmin && !isAccountPage" class="q-col-gutter-md q-mb-md row">
          <div class="col">
            <q-select
              v-model="form.data.role"
              dense
              filled
              hint="Set the user's permissions."
              label="Role"
              :option-label="(role: UserRole) => upperFirst(role)"
              :options="['viewer', 'operator', 'admin']"
              :readonly="form.readonly"
            />
          </div>
          <div class="col">
            <q-toggle
              v-model="form.data.disabled"
              color="negative"
              :disable="form.readonly"
              label="Disable"
            >
              <q-tooltip class="bg-negative text-white">
                Temporarily disable login access for this user.
              </q-tooltip>
            </q-toggle>
          </div>
        </div>
        <template v-if="user">
          <q-separator class="q-mb-sm" />
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
            <q-separator class="q-my-sm" />
            <q-btn-group flat spread>
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
                color="dark"
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
              @click="form.submit"
            />
          </q-btn-group>
        </template>
      </q-form>
    </q-card-section>
  </card-page>
</template>
