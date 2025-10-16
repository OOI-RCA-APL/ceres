<script lang="ts" setup>
import { useAuth } from '@/api/auth'
import { useEngine } from '@/api/engine'
import { isError } from '@/api/shared'
import { useNotify } from '@/notify'
import { ButtonWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ButtonWidget
}>()

const engine = useEngine()
const auth = useAuth()
const notify = useNotify()

let isRunning = $ref(false)

const action = $computed(() => {
  if (widget.address == null || widget.action == null) {
    return null
  }

  return engine.components.getAction(widget.address, widget.action)
})

const label = $computed(() => {
  if (widget.label) {
    return widget.label
  }

  if (widget.action) {
    return widget.action.replace(/[\-_]+/g, ' ').toUpperCase()
  }

  return widget.name
})

async function onClick() {
  if (!auth.isOperator) {
    return
  }

  try {
    isRunning = true
    const result = await engine.components.call(widget.address, widget.action, widget.arguments)
    if (isError(result)) {
      notify.error(`Action "${widget.action}" failed. ${JSON.stringify(result)}`, {
        timeout: 10000,
      })
    } else {
      notify.success(`Action "${widget.action}" completed successfully.`)
    }
  } finally {
    isRunning = false
  }
}
</script>

<template>
  <div class="text-center">
    <q-btn
      :color="widget.color"
      :disabled="!auth.isOperator || action == null"
      :flat="widget.styling === 'flat'"
      :label="label"
      :loading="isRunning"
      no-caps
      :outline="widget.styling === 'outlined'"
      @click="onClick"
    >
      <q-tooltip v-if="widget.address == null || widget.action == null">
        Button action is not configured.
      </q-tooltip>
      <q-tooltip v-else-if="action == null" class="bg-negative text-white">
        Button action {{ widget.address }}::action::{{ widget.action }} not found.
      </q-tooltip>
    </q-btn>
  </div>
</template>
