<script lang="ts" setup>
import { capitalize } from 'lodash-es'
import { onErrorCaptured } from 'vue'

import { useDialogs } from '@/dialogs'
import { CommonError, Escape, Failure, NotFoundError } from '@/errors'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'

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
      notify.error(`A failure occurred. Received "${error.error.type}".`)
      return false
    }

    if (error instanceof NotFoundError) {
      dialogs
        .show({
          title: `${capitalize(error.resourceType)} Not Found`,
          message: error.message,
          persistent: true,
          okLabel: 'Ok',
          // Going back from a page opened directly would leave the app.
          cancelLabel: navigation.canGoBack ? 'Go Back' : 'Close',
        })
        .onOk(() => void navigation.go('/'))
        .onCancel(() => {
          if (navigation.canGoBack) {
            navigation.back()
          }
        })
      return false
    }
  }

  console.error(error)
  notify.error('An unexpected error occurred. You may need to refresh the page.', {
    duration: 10000,
  })

  return false
})
</script>

<template>
  <slot />
</template>
