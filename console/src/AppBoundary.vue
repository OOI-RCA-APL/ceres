<script lang="ts" setup>
import { useDialogs } from '@/dialogs'
import { AppError, NotFoundError } from '@/errors'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { capitalize } from 'lodash'
import { onErrorCaptured } from 'vue'

const navigation = useNavigation()
const notify = useNotify()
const dialogs = useDialogs()

function processDoesNotExistError(error: NotFoundError) {
  dialogs
    .show({
      title: `${capitalize(error.resourceType)} Not Found`,
      message: error.message,
      persistent: true,
      ok: {
        color: 'primary',
        flat: true,
        label: 'Ok',
      },
      cancel: {
        color: 'grey',
        flat: true,
        label: 'Go Back',
      },
    })
    .onOk(() => void navigation.go('/'))
    .onCancel(() => navigation.back())
}

let isProcessingAppError = false

onErrorCaptured((error) => {
  if (isProcessingAppError) {
    return false
  }

  if (error instanceof AppError) {
    isProcessingAppError = true
    setTimeout(() => {
      isProcessingAppError = false
    })

    if (error instanceof NotFoundError) {
      processDoesNotExistError(error)
      return false
    }
  }

  console.error(error)
  notify.error('An unexpected error occurred. You may need to refresh the page.', {
    group: 'unexpected',
    position: 'bottom',
    timeout: 10000,
    badgeStyle: {
      display: 'none',
    },
  })

  return false
})
</script>

<template>
  <slot />
</template>
