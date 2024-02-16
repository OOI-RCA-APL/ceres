<script lang="ts" setup>
import { useDialogs } from '@/dialogs'
import { CommonError, Escape, Failure, NotFoundError } from '@/errors'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { capitalize } from 'lodash'
import { onErrorCaptured } from 'vue'

const navigation = useNavigation()
const notify = useNotify()
const dialogs = useDialogs()

let isProcessingCommonError = false

onErrorCaptured((error) => {
  if (isProcessingCommonError) {
    return false
  }

  if (error instanceof CommonError) {
    isProcessingCommonError = true
    setTimeout(() => {
      isProcessingCommonError = false
    })

    if (error instanceof Escape) {
      return false
    }

    if (error instanceof Failure) {
      console.log(error)
      notify.error(`Action not completed. Received "${error.error.type}".`)
      return false
    }

    if (error instanceof NotFoundError) {
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
