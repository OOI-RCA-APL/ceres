<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import { guard } from '@/errors'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'

const engine = useEngine()
const navigation = useNavigation()
const validate = useValidate()
const notify = useNotify()

// Where to land after signing in, carried in the query by the guard that sent the user here.
const redirect = $computed(() => {
  const value = navigation.route.query.redirect
  return typeof value === 'string' && value !== '' ? value : null
})

let isShowingPassword = $ref(false)

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

    if (redirect != null) {
      await navigation.go(redirect)
    } else {
      await navigation.go('/')
    }
  },
})
</script>

<template>
  <div class="mx-auto mt-12 w-full max-w-sm px-4">
    <div class="rounded-lg border border-default bg-elevated">
      <div class="px-4 py-3">
        <c-text element="h1" variant="title2">Login</c-text>
      </div>
      <c-separator />
      <form class="flex flex-col gap-2 p-4" @submit.prevent="form.submit()">
        <c-input
          v-model="form.data.username"
          autofocus
          class="w-full"
          :icon="icons.user"
          placeholder="Username"
        />
        <c-input
          v-model="form.data.password"
          class="w-full"
          :icon="icons.password"
          placeholder="Password"
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
        <c-button
          block
          class="mt-2"
          color="primary"
          :disabled="form.validation !== 'valid'"
          label="Submit"
          :loading="form.state === 'submitting'"
          type="submit"
        />
      </form>
    </div>
  </div>
</template>
