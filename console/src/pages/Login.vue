<script lang="ts" setup>
import CardPage from '@/components/CardPage.vue'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useStore } from '@/store'
import { useValidate } from '@/validate'
import { useQuasar } from 'quasar'

const props = withDefaults(
  defineProps<{
    redirect?: string | null
  }>(),
  {
    redirect: undefined,
  }
)

const store = useStore()
const navigation = useNavigation()
const validate = useValidate()
const quasar = useQuasar()

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
    const identity = await store.login(username, password)
    if (identity == null) {
      quasar.notify({
        message: `Failed to log in. Incorrect username/email or password.`,
        type: 'negative',
      })
    } else {
      quasar.notify({
        message: `Logged in as ${identity.user.username}.`,
        type: 'positive', // 'type' is an alias for 'color
        icon: icons.user,
      })
      if (props.redirect) {
        await navigation.go(props.redirect)
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
