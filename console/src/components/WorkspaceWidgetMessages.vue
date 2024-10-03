<script lang="ts" setup>
import { computed, watch } from 'vue'

import { Address, AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { MessagesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: MessagesWidget
}>()

const engine = useEngine()

const columns = $computed(() => [
  {
    label: 'Timestamp',
    name: 'timestamp',
    filtered: widget.filter.after != null || widget.filter.before != null,
  },
  { label: 'Address', name: 'address', filtered: widget.filter.address != null },
  { label: 'Direction', name: 'direction', filtered: widget.filter.direction != null },
  {
    label: 'Content',
    name: 'content',
    filtered: widget.filter.content_prefix != null || widget.filter.content_contains != null,
  },
])

const notify = useNotify()

let commandInputElement = $ref<HTMLInputElement | null>(null)

widget.commandHistoryIndex = null

watch(
  computed(() => widget.commandText),
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
  <record-view :columns="columns" :filter="widget.filter as any" type="message">
    <template #column-filter-timestamp>
      <div style="min-width: 200px">
        <div class="q-mb-xs">
          <schema-form-base
            v-model="widget.filter.after"
            :schema="{ title: 'After', type: 'string', format: 'date-time', optional: true }"
          />
        </div>
        <div>
          <schema-form-base
            v-model="widget.filter.before"
            :schema="{ title: 'Before', type: 'string', format: 'date-time', optional: true }"
          />
        </div>
      </div>
    </template>
    <template #column-filter-address>
      <div style="min-width: 200px">
        <schema-form-base
          :model-value="widget.filter.address?.toString()"
          :schema="{
            title: 'Address',
            type: 'string',
            enum: engine.components.all.flatMap((current) => [
              current.address.toString(),
              current.address.all().toString(),
            ]),
            optional: true,
          }"
          @update:model-value="
            (value) =>
              (widget.filter.address =
                value == null ? undefined : new AddressSelector(String(value)))
          "
        />
      </div>
    </template>
    <template #column-filter-direction>
      <div style="min-width: 200px">
        <schema-form-base
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
      <div style="min-width: 300px">
        <div class="q-mb-xs">
          <schema-form-base
            v-model="widget.filter.content_prefix"
            :schema="{ title: 'Prefix', type: 'string', optional: true }"
          />
        </div>
        <schema-form-base
          v-model="widget.filter.content_contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
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
