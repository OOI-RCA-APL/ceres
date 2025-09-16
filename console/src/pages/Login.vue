<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import { guard } from '@/errors'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'

const { redirect } = defineProps<{
  redirect?: string | null
}>()

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
    const identity = await guard(engine.auth.login(username, password), {
      'bad-credentials-error': () => {
        notify.error('Failed to log in. Incorrect username or password.')
      },
    })

    notify.success(`Logged in as "${identity.user.username}".`, {
      icon: icons.user,
    })

    if (redirect) {
      await navigation.go(redirect)
    } else {
      await navigation.go('/')
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
          label="Username"
          outlined
        >
          <template #prepend>
            <q-icon :name="icons.user" />
          </template>
        </q-input>
        <q-input
          v-model="form.data.password"
          class="q-mb-sm"
          dense
          label="Password"
          outlined
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
          :loading="form.state === 'submitting'"
          type="submit"
        />
      </q-form>
    </q-card-section>
  </card-page>
</template>
