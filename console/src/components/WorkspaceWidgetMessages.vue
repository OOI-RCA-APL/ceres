<script lang="ts" setup>
import { watch } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { MessagesWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: MessagesWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedCommandAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.commandAddress)
  return resolved == null ? null : Address.parse(resolved)
})

const resolvedFilter = $computed(() => ({
  ...widget.filter,
  address: workspace.resolveFilterAddress(widget.filter.address),
}))

const connectionEntries = $computed(() =>
  engine.components.all.flatMap((component) =>
    component.connections.map((connection) => [component.address, connection.name])
  )
)
const connectionModelValue = $computed(() => {
  if (resolvedCommandAddress == null || widget.commandConnection == null) {
    return null
  }

  return `${resolvedCommandAddress}::connections::${widget.commandConnection}`
})
const connectionOptions = $computed(() =>
  connectionEntries.map(([address, name]) => `${address}::connections::${name}`)
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

const columns = $computed(() => [
  {
    label: 'Connection',
    name: 'connection',
    filtered: widget.filter.connection != null,
    minWidth: 80,
  },
  {
    label: 'Direction',
    name: 'direction',
    filtered: widget.filter.direction != null,
    minWidth: 68,
  },
  {
    label: 'Data',
    name: 'data',
    filtered: (widget.filter.contains ?? widget.filter.prefix ?? widget.filter.suffix) != null,
  },
])

const notify = useNotify()

let commandInputElement = $ref<HTMLInputElement | null>(null)

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
  }
)

function onUpKeyPressed() {
  if (widget.commandHistory.length == 0) {
    widget.commandHistoryIndex = null
    return
  }

  if (widget.commandHistoryIndex == null) {
    widget.commandHistoryIndex = widget.commandHistory.length - 1
  } else {
    widget.commandHistoryIndex = Math.max(widget.commandHistoryIndex - 1, 0)
  }

  widget.commandText = widget.commandHistory[widget.commandHistoryIndex]
}

function onDownKeyPressed() {
  if (widget.commandHistory.length == 0 || widget.commandHistoryIndex == null) {
    widget.commandHistoryIndex = null
    return
  }

  if (widget.commandHistoryIndex >= widget.commandHistory.length - 1) {
    widget.commandHistoryIndex = null
    widget.commandText = ''
  } else {
    widget.commandHistoryIndex = Math.min(
      widget.commandHistoryIndex + 1,
      widget.commandHistory.length - 1
    )
    widget.commandText = widget.commandHistory[widget.commandHistoryIndex]
  }
}

const isConnected = true

async function submit() {
  if (
    resolvedCommandAddress == null ||
    widget.commandText == null ||
    widget.commandText.trim() === ''
  ) {
    return
  }

  if (!isConnected) {
    notify.error('Command failed to send. We cannot access the device at this time.')
    return
  }

  await engine.components.send(resolvedCommandAddress, widget.commandConnection, {
    data: widget.commandText,
  })

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
  <record-view :columns="columns" :filter="resolvedFilter" :widget>
    <template #column-filter-connection>
      <div style="min-width: 200px">
        <schema-form-value
          v-model="widget.filter.connection"
          :schema="{
            title: 'Connection',
            type: 'string',
            optional: true,
          }"
        />
      </div>
    </template>
    <template #column-filter-direction>
      <div style="min-width: 200px">
        <schema-form-value
          v-model="widget.filter.direction"
          :schema="{
            title: 'Direction',
            type: 'string',
            enum: ['send', 'receive'],
            optional: true,
          }"
        />
      </div>
    </template>
    <template #column-filter-data>
      <div class="column q-gutter-xs" style="min-width: 300px">
        <schema-form-value
          v-model="widget.dataDisplay"
          :schema="{
            title: 'Display',
            type: 'string',
            enum: ['default', 'hex', 'binary'],
          }"
        />
        <schema-form-value
          v-model="widget.filter.contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
        />
        <schema-form-value
          v-model="widget.filter.prefix"
          :schema="{ title: 'Prefix', type: 'string', optional: true }"
        />
      </div>
    </template>
    <template v-if="engine.auth.isAdmin" #default>
      <q-form @submit.prevent="submit">
        <q-separator />
        <div class="row">
          <q-input
            :ref="(ref: any) => (commandInputElement = ref?.getNativeElement() ?? null)"
            v-model="widget.commandText"
            borderless
            class="col-grow"
            :color="isConnected ? 'primary' : 'negative'"
            dense
            :disable="widget.commandAddress == null || !isConnected"
            icon="send"
            input-class="monospace-md commandText-nowrap"
            label="Send Message"
            submit
            @keydown.down.prevent="onDownKeyPressed"
            @keydown.enter.prevent="submit"
            @keydown.up.prevent="onUpKeyPressed"
          >
            <template #prepend>
              <q-icon :name="icons.chevronRight" />
            </template>
          </q-input>
          <div class="q-ml-xs q-pl-md q-pr-xs" style="min-width: 80px">
            <q-select
              borderless
              class="full-width"
              clearable
              dense
              hide-dropdown-icon
              label="To"
              :model-value="connectionModelValue"
              :options="connectionOptions"
              options-dense
              @update:model-value="onConnectionModelUpdate"
            />
          </div>
        </div>
      </q-form>
    </template>
  </record-view>
</template>
