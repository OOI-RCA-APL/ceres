<script lang="ts" setup>
import { AuthStore } from '@/auth'
import CommonText from '@/components/CommonText.vue'
import { useForm } from '@/form'
import { useValidate } from '@/validate'
import { useDialogPluginComponent, useQuasar } from 'quasar'

const { userId, auth } = defineProps<{
  userId: string
  auth: AuthStore
}>()

defineEmits([...useDialogPluginComponent.emits])

const quasar = useQuasar()
const validate = useValidate()

const { dialogRef, onDialogHide, onDialogOK } = useDialogPluginComponent()

const isOwnPassword = $computed(() => userId === auth.user?.id)

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
      ? await auth.changePassword(currentPassword, newPassword)
      : await auth.assignPassword(userId, newPassword)

    if (user == null) {
      quasar.notify({
        type: 'negative',
        message: 'Failed to change password. Current password is incorrect.',
      })
    } else {
      quasar.notify({
        type: 'positive',
        message: 'Password changed successfully.',
      })

      onDialogOK()
    }
  },
})

const isShowingCurrentPassword = $ref(false)
const isShowingNewPassword = $ref(false)
</script>

<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card class="q-dialog-plugin">
      <q-form :ref="form.bind" @submit="form.submit">
        <q-card-section>
          <common-text element="h2" variant="title1">Change Password</common-text>
        </q-card-section>
        <q-card-section class="q-pb-md q-pt-none">
          <q-input
            v-if="isOwnPassword"
            v-model="form.data.currentPassword"
            autofocus
            class="q-mb-sm"
            color="primary"
            dense
            filled
            label="Current Password"
            lazy-rules
            no-error-icon
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
            filled
            label="New Password"
            lazy-rules
            no-error-icon
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
        </q-card-section>
        <q-card-actions class="justify-end">
          <q-btn v-close-popup color="grey-8" flat label="Cancel" />
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
