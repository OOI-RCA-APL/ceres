<script lang="ts" setup>
import { QMenu } from 'quasar'
import { nextTick } from 'vue'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { isError } from '@/api/shared'
import CommonText from '@/components/CommonText.vue'
import WorkspaceWidgetButtonSettings from '@/components/WorkspaceWidgetButtonSettings.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { usePreferences } from '@/preferences'
import { isEmptyObjectSchema, useSchemaForm } from '@/schema-form'
import { deepClone, type Plain } from '@/utilities'
import { ButtonAction, useWorkspace } from '@/workspace'

const { button, first, last } = defineProps<{
  button: ButtonAction
  first: boolean
  last: boolean
}>()

const emit = defineEmits<{
  duplicate: []
  remove: []
  move: [by: number]
}>()

const access = useAccess()
const engine = useEngine()
const notify = useNotify()
const preferences = usePreferences()
const workspace = useWorkspace()

const resolvedAddress = $computed(() => {
  const resolved = workspace.resolveAddress(button.address)
  return resolved == null ? null : Address.parse(resolved)
})

const action = $computed(() => {
  if (resolvedAddress == null || button.action == null) {
    return null
  }

  return engine.components.getAction(resolvedAddress, button.action)
})

const canOperate = $computed(
  () => resolvedAddress != null && access.canOperate(resolvedAddress.toString())
)

const color = $computed(() => {
  if (button.color == null) {
    return preferences.isDarkModeEnabled ? 'grey-4' : 'grey-9'
  }

  return button.color
})

const textColor = $computed(() => {
  if (button.color == null && preferences.isDarkModeEnabled && button.styling == null) {
    return 'grey-10'
  }

  return undefined
})

let isRunning = $ref(false)
let isShowingArguments = $ref(false)
let isShowingSettings = $ref(false)

// The dots and a right-click open the same menu, held so the dots can open it wherever they are.
const menu = $ref<QMenu | null>(null)

// The arguments are edited on a copy of what the button holds, so a popup opened and dismissed
// leaves the button exactly as it was found. They are kept on submitting or on locking, which are
// the two ways a user says the arguments are the ones they meant.
let draft = $ref<unknown>({})

// Cast for the same reason `Procedure.vue` casts, since the form's value type describes any plain
// value at all and the compiler gives up walking into it.
const held = {
  value: () => draft as Plain,
  onUpdate: (value: unknown) => {
    draft = value
  },
}

const form = useSchemaForm({
  ...(held as any),
  schema: () => action?.arguments.json_schema ?? { type: 'object', properties: {} },
  async onSubmit(values: unknown) {
    button.arguments = deepClone(values) as Record<string, unknown>
    isShowingArguments = false
    await run(values)
  },
})

/** Whether the action asks for anything, which is what decides if pressing opens a popup.

Read off the schema rather than off the form, since what the form is holding is a copy left over
from the last time the popup was open and says nothing about what the action wants.
*/
const takesArguments = $computed(() => !isEmptyObjectSchema(form.getSchema([])))

/** Whether pressing opens something rather than running there and then. */
const opensDialog = $computed(() => (takesArguments && !button.locked) || button.confirm)

const label = $computed(() => {
  const named =
    button.label?.trim() ||
    button.action?.replace(/[\-_]+/g, ' ').toUpperCase() ||
    (button.address != null ? String(button.address) : 'Button')

  // A trailing ellipsis is how a control says it asks something before it acts, whether what it
  // opens is the arguments or the question of whether to go ahead at all.
  return opensDialog ? `${named}...` : named
})

// A confirmation is a question with an answer, so the dialog hands its answer back to whatever
// asked and the run either carries on or stops there.
let answerConfirm = $ref<((confirmed: boolean) => void) | null>(null)

function askConfirm(): Promise<boolean> {
  return new Promise((resolve) => {
    answerConfirm = resolve
  })
}

function confirmWith(confirmed: boolean) {
  answerConfirm?.(confirmed)
  answerConfirm = null
}

async function run(values: unknown) {
  if (!canOperate || resolvedAddress == null || button.action == null || action == null) {
    return
  }

  if (button.confirm && !(await askConfirm())) {
    return
  }

  try {
    isRunning = true
    const result = await engine.components.call(resolvedAddress, button.action, values)
    if (isError(result)) {
      notify.error(`Action "${button.action}" failed. ${JSON.stringify(result)}`, {
        timeout: 10000,
      })
    } else {
      notify.success(`Action "${button.action}" was executed successfully.`)
    }
  } finally {
    isRunning = false
  }
}

async function showArguments() {
  draft = deepClone(button.arguments)
  isShowingArguments = true

  // The form reads the copy it was just handed, and anything left over from an action that has
  // since changed shape is not worth carrying into a field that cannot hold it.
  await nextTick()
  if (!form.isValid) {
    form.reset()
  }
}

function onPress() {
  if (!canOperate || action == null) {
    return
  }

  if (takesArguments && !button.locked) {
    void showArguments()
    return
  }

  void run(deepClone(button.arguments))
}

/** Keep the arguments as they stand and stop asking for them, or start asking again.

Locking keeps what the popup is holding, since those are the arguments the button will go on
running with and there is nowhere left to say so once it stops asking. Unlocking keeps them too,
as the ones it will offer next time.
*/
function toggleLock() {
  button.arguments = deepClone(draft) as Record<string, unknown>
  button.locked = !button.locked

  // Locked, the popup has said everything it had to say, so it closes on the answer.
  if (button.locked) {
    isShowingArguments = false
  }
}
</script>

<template>
  <!-- A button carries its own menu, so the press that opens it must not reach the widget's, which
  is hung off the card around everything here. -->
  <div :class="$style.root" @contextmenu.stop>
    <q-btn
      :color="color"
      dense
      :disable="!canOperate || action == null"
      :flat="button.styling === 'flat'"
      :label="label"
      :loading="isRunning"
      no-caps
      :outline="button.styling === 'outlined'"
      :text-color="textColor"
      unelevated
      @click="onPress"
    >
      <q-tooltip v-if="button.address == null || button.action == null">
        Button action is not configured.
      </q-tooltip>
      <q-tooltip v-else-if="action == null" class="bg-negative text-white">
        Button action {{ resolvedAddress }}::action::{{ button.action }} not found.
      </q-tooltip>
      <q-tooltip v-else-if="button.tooltip" :class="`bg-${color} text-white`">
        {{ button.tooltip }}
      </q-tooltip>
      <!-- The arguments are asked for where the button is rather than in the middle of the screen,
      so the thing being run stays in view beside the form that runs it. -->
      <q-menu v-model="isShowingArguments" :class="$style.arguments" no-parent-event>
        <div class="q-pa-sm">
          <div class="items-center no-wrap q-mb-sm row">
            <common-text variant="th">{{ button.action }}</common-text>
            <q-space />
            <q-btn
              :color="button.locked ? 'primary' : undefined"
              dense
              flat
              :icon="button.locked ? icons.locked : icons.unlocked"
              round
              size="sm"
              @click="toggleLock"
            >
              <q-tooltip class="bg-primary text-white">
                {{
                  button.locked
                    ? 'Ask for these arguments each time'
                    : 'Keep these arguments and stop asking'
                }}
              </q-tooltip>
            </q-btn>
          </div>
          <q-card bordered class="q-mb-sm q-pa-sm" flat>
            <schema-form :form />
          </q-card>
          <schema-form-controls :execute-label="button.confirm ? 'Run...' : 'Run'" :form />
        </div>
      </q-menu>
    </q-btn>
    <q-btn
      :class="[$style.more, 'faded-hover']"
      dense
      flat
      :icon="icons.more"
      round
      size="6.5px"
      @click.stop="menu?.show($event)"
    />
    <q-menu ref="menu" context-menu>
      <q-list bordered dense>
        <q-item v-close-popup clickable dense @click="isShowingSettings = true">
          <q-item-section avatar>
            <q-icon :name="icons.settings" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Configure...</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-close-popup clickable dense :disable="!takesArguments" @click="showArguments()">
          <q-item-section avatar>
            <q-icon :name="icons.edit" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Arguments...</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-close-popup clickable dense @click="emit('duplicate')">
          <q-item-section avatar>
            <q-icon :name="icons.duplicate" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Duplicate</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item v-close-popup clickable dense :disable="first" @click="emit('move', -1)">
          <q-item-section avatar>
            <q-icon :name="icons.menuLeft" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Move Earlier</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-close-popup clickable dense :disable="last" @click="emit('move', 1)">
          <q-item-section avatar>
            <q-icon :name="icons.menuRight" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Move Later</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item v-close-popup clickable dense @click="emit('remove')">
          <q-item-section avatar>
            <q-icon :name="icons.delete" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Delete</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
    <q-dialog :model-value="isShowingSettings" @update:model-value="isShowingSettings = false">
      <q-card bordered :class="$style.settings" flat>
        <div class="q-pa-md">
          <common-text class="q-mb-sm" variant="title1">Button</common-text>
          <workspace-widget-button-settings :button />
        </div>
        <q-separator />
        <q-btn
          class="full-width"
          color="primary"
          dense
          flat
          label="Done"
          @click="isShowingSettings = false"
        />
      </q-card>
    </q-dialog>
    <q-dialog :model-value="answerConfirm != null" @update:model-value="confirmWith(false)">
      <q-card bordered :class="$style.confirm" flat>
        <div class="q-pa-md">
          <common-text class="q-mb-xs" variant="title1">Run {{ button.action }}?</common-text>
          <common-text variant="description">
            This runs {{ button.action }} on {{ resolvedAddress }}.
          </common-text>
        </div>
        <q-separator />
        <div class="q-col-gutter-sm q-pa-sm row">
          <div class="col">
            <q-btn class="full-width" dense flat label="Cancel" @click="confirmWith(false)" />
          </div>
          <div class="col">
            <q-btn
              class="full-width"
              color="primary"
              dense
              label="Run"
              unelevated
              @click="confirmWith(true)"
            />
          </div>
        </div>
      </q-card>
    </q-dialog>
  </div>
</template>

<style lang="scss" module>
.root {
  position: relative;
  display: inline-flex;
}

// The dots sit over the button's own corner rather than beside it, so a bar of buttons is a bar of
// buttons and arranging one costs no room until it is reached for.
.more {
  position: absolute;
  top: -6px;
  right: -6px;
  z-index: 1;
  opacity: 0;
  transition: opacity 0.15s;
}

.root:hover .more {
  opacity: 1;
}

.arguments {
  max-width: 420px;
  width: 100%;
}

.settings {
  max-width: 400px;
  width: 100%;
}

.confirm {
  max-width: 360px;
  width: 100%;
}
</style>
