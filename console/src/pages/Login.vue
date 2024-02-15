<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'

const { redirect } = withDefaults(
  defineProps<{
    redirect?: string | null
  }>(),
  {
    redirect: undefined,
  }
)

const engine = useEngine()
const navigation = useNavigation()
const validate = useValidate()
const notify = useNotify()

const isShowingPassword = $ref(false)

const form = useForm({
  data: {
    username: '',
    password: '',
  },
  validators: {
    username: validate.isNotBlank(),
    password: validate.isNotBlank(),
  },
  async onSubmit({ username, password }) {
    const identity = await engine.auth.login(username, password)
    if (identity == null) {
      notify.error('Failed to log in. Incorrect username/email or password.')
    } else {
      notify.success(`Logged in as "${identity.user.username}".`, {
        icon: icons.user,
      })
      if (redirect) {
        await navigation.go(redirect)
      } else {
        await navigation.go('/')
      }
    }
  },
})
</script>

<template>
  <card-page title="Login">
    <q-card-section>
      <q-form @submit="form.submit">
        <q-input
          v-model="form.data.username"
          autofocus
          class="q-mb-sm"
          dense
          filled
          label="Username"
        >
          <template #prepend>
            <q-icon :name="icons.user" />
          </template>
        </q-input>
        <q-input
          v-model="form.data.password"
          class="q-mb-sm"
          dense
          filled
          label="Password"
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
        <q-btn
          class="full-width q-mt-sm"
          color="primary"
          :disable="form.validation !== 'valid'"
          label="Submit"
          type="submit"
        />
      </q-form>
    </q-card-section>
  </card-page>
</template>
