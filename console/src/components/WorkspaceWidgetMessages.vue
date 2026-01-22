<script lang="ts" setup>
import { watch } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { MessagesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MessagesWidget
}>()

const engine = useEngine()

const columns = $computed(() => [
  {
    label: 'Connection',
    name: 'connection',
    filtered: widget.filter.connection != null,
    minWidth: 76,
  },
  {
    label: 'Direction',
    name: 'direction',
    filtered: widget.filter.direction != null,
    minWidth: 76,
  },
  {
    label: 'Content',
    name: 'content',
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
    widget.commandAddress == null ||
    widget.commandText == null ||
    widget.commandText.trim() === ''
  ) {
    return
  }

  if (!isConnected) {
    notify.error('Command failed to send. We cannot access the device at this time.')
    return
  }

  await engine.components.call(widget.commandAddress, 'send', {
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
  <record-view :columns="columns" :filter="widget.filter" :widget>
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
    <template #column-filter-content>
      <div class="column q-gutter-xs" style="min-width: 300px">
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
    <template v-if="engine.auth.isOperator" #default>
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
              clearable
              dense
              hide-dropdown-icon
              label="To"
              :model-value="widget.commandAddress?.toString() ?? null"
              :options="
                engine.components.all
                  .filter((current) => current.roles.includes('connection'))
                  .map((current) => current.address.toString())
              "
              options-dense
              @update:model-value="
                (value) =>
                  (widget.commandAddress = value == null ? null : new Address(String(value)))
              "
            />
          </div>
        </div>
      </q-form>
    </template>
  </record-view>
</template>
