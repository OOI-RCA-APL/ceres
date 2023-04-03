<script lang="ts" setup>
import { Address } from '@/address'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { useQuasar } from 'quasar'
import { computed, watch } from 'vue'
import Zod from 'zod'

const { address } = defineProps<{
  label: string
  address: Address
}>()

const emit = defineEmits<{
  (emit: 'send', command: string): void
}>()

const quasar = useQuasar()

const StateSchema = Zod.object({
  command: Zod.string().default(''),
  history: Zod.array(Zod.string()).default(() => []),
  historyIndex: Zod.number().nullable().default(null),
})

let element = $ref<HTMLInputElement | null>(null)

const state = usePersisted({
  schema: StateSchema,
  methods: [
    {
      type: 'local-storage',
      key: `state/command-input/${address}`,
    },
  ],
})

state.historyIndex = null

watch(
  computed(() => state.command),
  () => {
    setTimeout(() => {
      if (state.historyIndex != null && state.command !== state.history[state.historyIndex]) {
        state.historyIndex = null
      }
    }, 0)
  }
)

function onUpKeyPressed() {
  if (state.history.length == 0) {
    state.historyIndex = null
    return
  }

  if (state.historyIndex == null) {
    state.historyIndex = state.history.length - 1
  } else {
    state.historyIndex = Math.max(state.historyIndex - 1, 0)
  }

  state.command = state.history[state.historyIndex]
}

function onDownKeyPressed() {
  if (state.history.length == 0 || state.historyIndex == null) {
    state.historyIndex = null
    return
  }

  if (state.historyIndex >= state.history.length - 1) {
    state.historyIndex = null
    state.command = ''
  } else {
    state.historyIndex = Math.min(state.historyIndex + 1, state.history.length - 1)
    state.command = state.history[state.historyIndex]
  }
}

const isConnected = true

async function submit() {
  if (state.command.trim() === '') {
    return
  }

  if (!isConnected) {
    quasar.notify({
      type: 'negative',
      message: 'Command failed to send. We cannot access the device at this time.',
    })

    return
  }

  emit('send', state.command.trim())
  if (state.history.length === 0 || state.command !== state.history[state.history.length - 1]) {
    state.history.push(state.command.trim())
  }

  state.historyIndex = null
  state.command = ''
}
</script>

<template>
  <q-form @submit.prevent="submit">
    <q-input
      :ref="(ref: any) => (element = ref?.getNativeElement() ?? null)"
      v-model="state.command"
      :color="isConnected ? 'primary' : 'negative'"
      dense
      input-class="monospace text-nowrap"
      :label="label"
      outlined
      @keydown.down.prevent="onDownKeyPressed"
      @keydown.up.prevent="onUpKeyPressed"
    >
      <template v-if="isConnected" #append>
        <q-btn color="primary" dense flat :icon="icons.send" type="button" @click="submit" />
      </template>
    </q-input>
  </q-form>
</template>
