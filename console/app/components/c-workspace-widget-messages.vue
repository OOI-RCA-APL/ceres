<script lang="ts" setup>
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { useWorkspace } from '@/workspace'
import type { MessagesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MessagesWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()
const access = useAccess()

const resolvedCommandAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.commandAddress)
  return resolved == null ? null : Address.parse(resolved.toString())
})

// Only connections the workspace can address and the user may operate. Sending is an operation
// on the component addressed, and either refusal would come back from the engine anyway, so
// offering one is a dead end dressed up as a choice.
const connectionEntries = $computed(() =>
  engine.components.all
    .filter(
      (component) =>
        workspace.isWithinScope(component.address) &&
        access.canOperate(component.address.toString()),
    )
    .flatMap((component) =>
      component.connections.map((connection) => [component.address, connection.name] as const),
    ),
)
const connectionModelValue = $computed(() => {
  if (resolvedCommandAddress == null || widget.commandConnection == null) {
    return null
  }

  return `${resolvedCommandAddress}::connections::${widget.commandConnection}`
})
const connectionOptions = $computed(() =>
  connectionEntries.map(([address, name]) => `${address}::connections::${name}`),
)

// A widget with no target starts on the first connection the workspace can reach, which on
// a component-bound workspace is almost always the one meant. A target that no longer
// exists, from a connection that has gone or a workspace that has moved, falls back the
// same way rather than sitting there naming nothing.
watch(
  () => [connectionOptions, connectionModelValue] as const,
  ([options, current]) => {
    if (current != null && options.includes(current)) {
      return
    }

    if (current == null && options.length === 0) {
      return
    }

    onConnectionModelUpdate(options[0] ?? null)
  },
  { immediate: true },
)

function onConnectionModelUpdate(option: string | null) {
  const [address, namespace, name] = option?.split('::') ?? []
  if (address == null || namespace !== 'connections' || name == null) {
    widget.commandAddress = null
    widget.commandConnection = null
  } else {
    widget.commandAddress = new Address(address)
    widget.commandConnection = name
  }
}

const columns = [
  { label: 'Connection', name: 'connection', minWidth: 80 },
  { label: 'Direction', name: 'direction', minWidth: 68 },
  { label: 'Data', name: 'data' },
]

const notify = useNotify()

widget.commandHistoryIndex = null

watch(
  () => widget.commandText,
  () => {
    setTimeout(() => {
      if (
        widget.commandHistoryIndex != null &&
        widget.commandText !== widget.commandHistory[widget.commandHistoryIndex]
      ) {
        widget.commandHistoryIndex = null
      }
    }, 0)
  },
)

function onUpKeyPressed() {
  if (widget.commandHistory.length === 0) {
    widget.commandHistoryIndex = null
    return
  }

  if (widget.commandHistoryIndex == null) {
    widget.commandHistoryIndex = widget.commandHistory.length - 1
  } else {
    widget.commandHistoryIndex = Math.max(widget.commandHistoryIndex - 1, 0)
  }

  widget.commandText = widget.commandHistory[widget.commandHistoryIndex] ?? ''
}

function onDownKeyPressed() {
  if (widget.commandHistory.length === 0 || widget.commandHistoryIndex == null) {
    widget.commandHistoryIndex = null
    return
  }

  if (widget.commandHistoryIndex >= widget.commandHistory.length - 1) {
    widget.commandHistoryIndex = null
    widget.commandText = ''
  } else {
    widget.commandHistoryIndex = Math.min(
      widget.commandHistoryIndex + 1,
      widget.commandHistory.length - 1,
    )
    widget.commandText = widget.commandHistory[widget.commandHistoryIndex] ?? ''
  }
}

// Only an explicit refusal blocks a send, so a target whose status has not arrived yet, or one
// still connecting, stays writable rather than disabling the input on every reconnect.
const isConnected = $computed(() => {
  if (resolvedCommandAddress == null) {
    return true
  }

  const status = engine.statuses.get(resolvedCommandAddress)
  if (status == null) {
    return true
  }

  if (!status.running) {
    return false
  }

  const connectivity =
    status.connectivity ??
    status.connections.find((connection) => connection.name === widget.commandConnection)
      ?.connectivity

  return connectivity !== 'disconnected'
})

async function submit() {
  if (
    resolvedCommandAddress == null ||
    widget.commandText == null ||
    widget.commandText.trim() === ''
  ) {
    return
  }

  // Checked again at the point of sending, the target having been chosen before whatever access
  // change may have landed since.
  if (!access.canOperate(resolvedCommandAddress.toString())) {
    notify.error('You do not have permission to send on this connection.')
    return
  }

  if (!isConnected) {
    notify.error('Command failed to send. We cannot access the device at this time.')
    return
  }

  await engine.messages.send(
    resolvedCommandAddress,
    widget.commandConnection ?? '',
    widget.commandText,
  )

  if (
    widget.commandHistory.length === 0 ||
    widget.commandText !== widget.commandHistory[widget.commandHistory.length - 1]
  ) {
    widget.commandHistory.push(widget.commandText.trim())
  }

  widget.commandHistoryIndex = null
  widget.commandText = ''
}
</script>

<template>
  <c-record-view :columns="columns" :widget>
    <template v-if="connectionOptions.length > 0" #default>
      <form @submit.prevent="submit">
        <c-separator />
        <div class="flex items-center">
          <c-icon class="text-muted mx-1 shrink-0" :name="icons.chevronRight" size="16" />
          <input
            v-model="widget.commandText"
            class="min-w-0 grow bg-transparent py-1.5 font-mono text-xs outline-none"
            :disabled="widget.commandAddress == null || !isConnected"
            placeholder="Send Message"
            spellcheck="false"
            type="text"
            @keydown.down.prevent="onDownKeyPressed"
            @keydown.enter.prevent="submit"
            @keydown.up.prevent="onUpKeyPressed"
          />
          <div class="ml-1 min-w-20 shrink-0 pr-1 pl-4">
            <c-select-menu
              class="w-full"
              :items="[...connectionOptions]"
              :model-value="connectionModelValue ?? undefined"
              placeholder="To"
              size="xs"
              :ui="{ base: 'font-mono text-[10px]' }"
              variant="ghost"
              @update:model-value="(value: string) => onConnectionModelUpdate(value ?? null)"
            />
          </div>
        </div>
      </form>
    </template>
  </c-record-view>
</template>
