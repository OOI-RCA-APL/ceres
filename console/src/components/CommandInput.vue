<script lang="ts" setup>
import { Address } from '@/address'
import icons from '@/icons'
import { useInterfaceContext } from '@/interface'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { computed, watch } from 'vue'
import Zod from 'zod'

const { address } = defineProps<{
  address: Address
}>()

const emit = defineEmits<{
  (emit: 'send', command: string): void
}>()

const context = useInterfaceContext()
const notify = useNotify()

const StateSchema = Zod.object({
  text: Zod.string().default(''),
  history: Zod.array(Zod.string()).default(() => []),
  historyIndex: Zod.number().nullable().default(null),
})

let element = $ref<HTMLInputElement | null>(null)

const state = usePersisted({
  schema: StateSchema,
  methods: computed(() => [
    {
      type: 'local-storage',
      key: [context.key, 'state', 'command-input', address],
    },
  ]),
})

state.historyIndex = null

watch(
  computed(() => state.text),
  () => {
    setTimeout(() => {
      if (state.historyIndex != null && state.text !== state.history[state.historyIndex]) {
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

  state.text = state.history[state.historyIndex]
}

function onDownKeyPressed() {
  if (state.history.length == 0 || state.historyIndex == null) {
    state.historyIndex = null
    return
  }

  if (state.historyIndex >= state.history.length - 1) {
    state.historyIndex = null
    state.text = ''
  } else {
    state.historyIndex = Math.min(state.historyIndex + 1, state.history.length - 1)
    state.text = state.history[state.historyIndex]
  }
}

const isConnected = true

async function submit() {
  if (state.text.trim() === '') {
    return
  }

  if (!isConnected) {
    notify.error('Command failed to send. We cannot access the device at this time.')
    return
  }

  emit('send', state.text.trim())
  if (state.history.length === 0 || state.text !== state.history[state.history.length - 1]) {
    state.history.push(state.text.trim())
  }

  state.historyIndex = null
  state.text = ''
}
</script>

<template>
  <q-form @submit.prevent="submit">
    <q-input
      :ref="(ref: any) => (element = ref?.getNativeElement() ?? null)"
      v-model="state.text"
      borderless
      :color="isConnected ? 'primary' : 'negative'"
      dense
      icon="send"
      input-class="monospace-md text-nowrap"
      label="Send Message"
      @keydown.down.prevent="onDownKeyPressed"
      @keydown.up.prevent="onUpKeyPressed"
    >
      <template #prepend>
        <q-icon :name="icons.chevronRight" size="20px" />
      </template>
    </q-input>
  </q-form>
</template>
