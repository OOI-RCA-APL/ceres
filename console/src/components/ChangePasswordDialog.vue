<script lang="ts" setup>
import { Engine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import { useForm } from '@/form'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'
import { useDialogPluginComponent } from 'quasar'

const { userId, engine } = defineProps<{
  userId: string
  engine: Engine
}>()

defineEmits([...useDialogPluginComponent.emits])

const notify = useNotify()
const validate = useValidate()

const { dialogRef, onDialogHide, onDialogOK } = useDialogPluginComponent()

const isOwnPassword = $computed(() => userId === engine.auth.user?.id)

const form = useForm({
  data: {
    currentPassword: '',
    newPassword: '',
  },
  validators: {
    currentPassword: (currentPassword) =>
      !isOwnPassword || currentPassword !== '' || 'Your current password is required.',
    newPassword: validate.isNotEmpty('Enter a new password.'),
  },
  onSubmit: async ({ currentPassword, newPassword }) => {
    const user = isOwnPassword
      ? await engine.auth.changePassword(currentPassword, newPassword)
      : await engine.auth.assignPassword(userId, newPassword)

    if (user == null) {
      notify.error('Failed to change password. Current password is incorrect')
    } else {
      notify.success(`Password for "${user.username}" changed successfully.`)
      onDialogOK()
    }
  },
})

const isShowingCurrentPassword = $ref(false)
const isShowingNewPassword = $ref(false)
</script>

<template>
  <q-dialog ref="dialogRef" persistent @hide="onDialogHide">
    <q-card class="q-dialog-plugin">
      <div class="q-px-md">
        <common-text element="h2" variant="title1">Change Password</common-text>
      </div>
      <q-form :ref="form.bind" @submit="form.submit">
        <div class="q-pt-none q-px-md">
          <q-input
            v-if="isOwnPassword"
            v-model="form.data.currentPassword"
            autofocus
            class="q-mb-sm"
            color="primary"
            dense
            label="Current Password"
            lazy-rules
            no-error-icon
            outlined
            :type="isShowingCurrentPassword ? 'text' : 'password'"
          >
            <template #append>
              <q-icon
                class="cursor-pointer"
                :name="isShowingCurrentPassword ? 'visibility' : 'visibility_off'"
                @click="isShowingCurrentPassword = !isShowingCurrentPassword"
              />
            </template>
          </q-input>
          <q-input
            v-model="form.data.newPassword"
            color="primary"
            dense
            label="New Password"
            lazy-rules
            no-error-icon
            outlined
            :type="isShowingNewPassword ? 'text' : 'password'"
          >
            <template #append>
              <q-icon
                class="cursor-pointer"
                :name="isShowingNewPassword ? 'visibility' : 'visibility_off'"
                @click="isShowingNewPassword = !isShowingNewPassword"
              />
            </template>
          </q-input>
        </div>
        <q-card-actions class="justify-end">
          <q-btn v-close-popup color="grey" flat label="Cancel" />
          <q-btn
            color="primary"
            :disable="form.validation !== 'valid'"
            flat
            label="Submit"
            :loading="form.state === 'submitting'"
            type="submit"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
