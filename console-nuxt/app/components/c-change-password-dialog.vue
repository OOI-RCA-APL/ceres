<script lang="ts">
export type ChangePasswordDialogProps = {
  userId: string
}
</script>

<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'

const { userId } = defineProps<ChangePasswordDialogProps>()

const emit = defineEmits<{ close: [boolean] }>()

const engine = useEngine()
const notify = useNotify()
const validate = useValidate()

// An administrator assigning someone else's password does not know the old one, so only the
// account's own owner is asked for it.
const isOwnPassword = $computed(() => userId === engine.auth.user?.id)

let isShowingCurrentPassword = $ref(false)
let isShowingNewPassword = $ref(false)

const form = useForm({
  data: {
    currentPassword: '',
    newPassword: '',
  },
  validators: {
    currentPassword: (currentPassword: string) =>
      !isOwnPassword || currentPassword !== '' || 'Your current password is required.',
    newPassword: validate.isNotEmpty('Enter a new password.'),
  },
  async onSubmit({ currentPassword, newPassword }) {
    const user = isOwnPassword
      ? await engine.auth.changePassword(currentPassword, newPassword)
      : await engine.auth.assignPassword(userId, newPassword)

    if (user == null) {
      notify.error('Failed to change password. Current password is incorrect.')
      return
    }

    notify.success(`Password for "${user.username}" changed successfully.`)
    emit('close', true)
  },
})
</script>

<template>
  <c-modal
    :dismissible="false"
    title="Change Password"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <form class="flex flex-col gap-2" @submit.prevent="form.submit()">
        <c-input
          v-if="isOwnPassword"
          v-model="form.data.currentPassword"
          autofocus
          class="w-full"
          :icon="icons.password"
          placeholder="Current Password"
          :type="isShowingCurrentPassword ? 'text' : 'password'"
        >
          <template #trailing>
            <c-button
              color="neutral"
              :icon="isShowingCurrentPassword ? icons.view : icons.locked"
              size="xs"
              variant="link"
              @click="isShowingCurrentPassword = !isShowingCurrentPassword"
            />
          </template>
        </c-input>
        <c-input
          v-model="form.data.newPassword"
          :autofocus="!isOwnPassword"
          class="w-full"
          :icon="icons.password"
          placeholder="New Password"
          :type="isShowingNewPassword ? 'text' : 'password'"
        >
          <template #trailing>
            <c-button
              color="neutral"
              :icon="isShowingNewPassword ? icons.view : icons.locked"
              size="xs"
              variant="link"
              @click="isShowingNewPassword = !isShowingNewPassword"
            />
          </template>
        </c-input>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <c-button color="neutral" variant="ghost" @click="emit('close', false)">Cancel</c-button>
        <c-button
          :disabled="form.validation !== 'valid'"
          :loading="form.state === 'submitting'"
          @click="form.submit()"
        >
          Submit
        </c-button>
      </div>
    </template>
  </c-modal>
</template>
