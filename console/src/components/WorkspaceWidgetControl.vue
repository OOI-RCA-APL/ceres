<script lang="ts" setup>
import { escape, startCase } from 'lodash-es'
import { QMenu } from 'quasar'
import { v7 } from 'uuid'
import { nextTick } from 'vue'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { isError } from '@/api/shared'
import CommonText from '@/components/CommonText.vue'
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import WorkspaceWidgetControlSettings from '@/components/WorkspaceWidgetControlSettings.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { useNotify } from '@/notify'
import { usePreferences } from '@/preferences'
import { isEmptyObjectSchema, useSchemaForm } from '@/schema-form'
import { displayDuration } from '@/time'
import { deepClone, highlight, type Plain } from '@/utilities'
import { ButtonAction, useWorkspace } from '@/workspace'

const { button } = defineProps<{
  button: ButtonAction
}>()

const emit = defineEmits<{
  duplicate: []
  remove: []

  /** Insert a fresh button beside this one, on whichever side was asked for. */
  addBefore: []
  addAfter: []
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

// The full path of what pressing runs, written the way an address is. The popup only opens once
// there is an action to run so the parts are there to name.
const actionPath = $computed(() => `${resolvedAddress}::actions::${button.action}`)

const canOperate = $computed(
  () => resolvedAddress != null && access.canOperate(resolvedAddress.toString())
)

// A fresh button holds no action yet so pressing it opens the settings that give it one.
const isConfigured = $computed(() => button.address != null && button.action != null)

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

// While the menu is open the pointer is on the menu rather than the button so without this the
// dots that opened it would fade away under it.
let isShowingMenu = $ref(false)

// The arguments are edited on a copy of what the button holds so a popup opened and dismissed
// leaves the button exactly as it was found. They are kept on submitting or on locking, which are
// the two ways a user says the arguments are the ones they meant.
let draft = $ref<unknown>({})

// Cast for the same reason `Procedure.vue` casts since the form's value type describes any plain
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
  title: 'Arguments',
  // The popup stays put while the action runs, with the button and the "Execute" control both
  // showing the wait so what was pressed and what it is doing stay in view together.
  async onSubmit(values: unknown) {
    button.arguments = deepClone(values) as Record<string, unknown>
    await run(values)
  },
})

/** Whether the action takes arguments, which decides whether pressing opens a popup.

Read off the schema rather than the form since the form holds a stale copy from the last time
the popup was open.
*/
const takesArguments = $computed(() => !isEmptyObjectSchema(form.getSchema([])))

/** Whether pressing opens something rather than running there and then. */
const opensDialog = $computed(() => (takesArguments && !button.locked) || button.confirm)

const named = $computed(
  () =>
    button.label?.trim() ||
    (button.action != null ? startCase(button.action) : '') ||
    (button.address != null ? String(button.address) : 'Button')
)

// A button is renamed on the bar the way a tab is, the field offered under shift and made real by
// clicking into it. Renaming touches only the label so the action underneath keeps its own name.
const { shift: shiftHeld } = useModifiers()
let isLabelHovered = $ref(false)
let isEditingLabel = $ref(false)
const isLabelOffered = $computed(() => isEditingLabel || (shiftHeld.value && isLabelHovered))

function renameButton(name: string) {
  button.label = name
}

// A confirmation is a question with an answer so the dialog hands its answer back to whatever
// asked and the run either carries on or stops there.
let answerConfirm = $ref<((confirmed: boolean) => void) | null>(null)

// The arguments the confirmed run would send, highlighted for the dialog, or null with none.
let confirmingArguments = $ref<string | null>(null)

function askConfirm(values: unknown): Promise<boolean> {
  const hasArguments =
    values != null && typeof values === 'object' && Object.keys(values).length > 0
  confirmingArguments = hasArguments ? highlight(stringify(values), 'yaml') : null

  return new Promise((resolve) => {
    answerConfirm = resolve
  })
}

function confirmWith(confirmed: boolean) {
  answerConfirm?.(confirmed)
  answerConfirm = null
}

// The controller of the call in flight, held so a cancel can reach it. Aborting the request is
// aborting the action since the engine cancels a procedure whose caller has gone away.
let running = $ref<AbortController | null>(null)

/** One toast that follows the whole run.

Shown with a spinner, the running time, and an "Abort" for as long as the action runs, then turned
positive, grey, or negative by how the run ended. It waits out a pointer resting on it, since a
toast that slips away mid-read has said nothing.
*/
function createRunToast(controller: AbortController) {
  const startedAt = Date.now()
  const marker = `action-toast-${v7()}`
  let isHovered = false

  const elapsed = () => displayDuration((Date.now() - startedAt) / 1000, { short: true })

  // The message is the path of what is running, the same as the popup's title, with the spinner
  // trailing it. Said as markup because the toast is the one place a component cannot stand, and
  // the path holds nothing that needs escaping.
  const spinner = '<i class="mdi mdi-loading mdi-spin q-ml-xs"></i>'

  const update = notify.show({
    group: false,
    timeout: 0,
    html: true,
    color: 'primary',
    classes: marker,
    message: `<span class="monospace-sm">${actionPath}</span> ${spinner}`,
    caption: elapsed(),
    actions: [
      {
        label: 'Abort',
        color: 'white',
        dense: true,
        noCaps: true,
        noDismiss: true,
        handler: () => controller.abort(),
      },
    ],
  })

  const ticker = setInterval(() => update({ caption: elapsed() }), 1000)

  // The notification is portaled and rendered a beat later so the hover listeners are attached
  // once it exists. Updates reuse the same element so they hold for the toast's whole life.
  setTimeout(() => {
    const element = document.querySelector(`.${marker}`)
    element?.addEventListener('pointerenter', () => (isHovered = true))
    element?.addEventListener('pointerleave', () => (isHovered = false))
  }, 100)

  function settle(color: string, message: string, holdFor: number) {
    clearInterval(ticker)
    update({
      spinner: false,
      color,
      textColor: 'white',
      // The toast was opened as markup and stays markup through updates, and a failure's detail
      // quotes whatever the server said so the text is escaped rather than trusted.
      message: escape(message),
      caption: elapsed(),
      actions: [
        {
          icon: icons.close,
          color,
          textColor: 'white',
          dense: true,
          size: '13px',
          round: true,
          class: 'faded-hover',
        },
      ],
    })

    // The toast leaves on its own only once it has been left alone so a pointer resting on it
    // holds it, and leaving gives it a moment before the clock resumes.
    let remaining = holdFor
    const tick = 250
    const leaving = setInterval(() => {
      if (isHovered) {
        remaining = Math.max(remaining, 1000)
        return
      }

      remaining -= tick
      if (remaining <= 0) {
        clearInterval(leaving)
        update()
      }
    }, tick)
  }

  return {
    succeeded: () => settle('positive', `Action "${button.action}" succeeded.`, 3000),
    canceled: () => settle('grey-7', `Action "${button.action}" was canceled.`, 3000),
    failed: (detail: string) =>
      settle('negative', `Action "${button.action}" failed. ${detail}`, 8000),
  }
}

async function run(values: unknown) {
  if (!canOperate || resolvedAddress == null || button.action == null || action == null) {
    return
  }

  if (button.confirm && !(await askConfirm(values))) {
    return
  }

  const controller = new AbortController()
  running = controller
  const toast = createRunToast(controller)

  try {
    isRunning = true
    const result = await engine.components.call(resolvedAddress, button.action, values, {
      signal: controller.signal,
    })

    if (isError(result)) {
      toast.failed(JSON.stringify(result))
    } else {
      toast.succeeded()
    }
  } catch (error) {
    // Asked for so not a failure. Anything else is one and stays thrown.
    if (!controller.signal.aborted) {
      toast.failed(String(error))
      throw error
    }

    toast.canceled()
  } finally {
    isRunning = false
    running = null
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

// While the action runs, "Cancel" cancels the action. At rest it closes the popup, which is all
// there is left to back out of.
function onCancel() {
  if (running != null) {
    running.abort()
    return
  }

  isShowingArguments = false
}

function onPress(event: MouseEvent) {
  // A locked button runs without ever opening the popup so the button itself is the one cancel
  // surface every flow has. Pressing it while the action runs aborts the action.
  if (running != null) {
    running.abort()
    return
  }

  // Shift is asking for the rename, the same as it does on a tab.
  if (event.shiftKey) {
    isEditingLabel = true
    return
  }

  if (!isConfigured) {
    isShowingSettings = true
    return
  }

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

Locking keeps what the popup is holding since those are the arguments the button will go on
running with and there is nowhere left to say so once it stops asking. Unlocking keeps them too,
as the ones it will offer next time. The popup stays open either way so the choice can be
reconsidered where it was made.
*/
function toggleLock() {
  button.arguments = deepClone(draft) as Record<string, unknown>
  button.locked = !button.locked
}
</script>

<template>
  <!-- A button carries its own menu so the press that opens it must not reach the widget's, which
  is hung off the card around everything here. -->
  <div :class="$style.root" @contextmenu.stop>
    <q-btn
      :color="color"
      dense
      :disable="isConfigured && (!canOperate || action == null)"
      :flat="button.styling === 'flat'"
      no-caps
      :outline="button.styling === 'outlined'"
      :text-color="textColor"
      unelevated
      @click="onPress"
    >
      <!-- Drawn beside the label rather than through the loading state since a loading button
      swallows its clicks and the press while running is the abort. -->
      <q-spinner v-if="isRunning" class="q-mr-xs" />
      <span @pointerenter="isLabelHovered = true" @pointerleave="isLabelHovered = false">
        <inline-name-edit
          :claim="isEditingLabel"
          :editing="isLabelOffered"
          :name="named"
          @rename="renameButton"
          @update:editing="(value: boolean) => (isEditingLabel = value)"
        />
      </span>
      <!-- The chevron is how a control says it asks something before it acts, whether what it
      opens is the arguments or the question of whether to go ahead at all. -->
      <q-icon v-if="opensDialog" :class="$style.asks" :name="icons.chevronDown" />
      <q-tooltip v-if="isRunning" class="bg-warning text-dark">Press to Abort</q-tooltip>
      <q-tooltip v-else-if="!isConfigured">
        Button action is not configured. Press to configure.
      </q-tooltip>
      <q-tooltip v-else-if="action == null" class="bg-negative text-white">
        Button action {{ resolvedAddress }}::action::{{ button.action }} not found.
      </q-tooltip>
      <q-tooltip v-else-if="button.tooltip" :class="`bg-${color} text-white`">
        {{ button.tooltip }}
      </q-tooltip>
      <!-- The arguments are asked for where the button is rather than in the middle of the screen,
      so the thing being run stays in view beside the form that runs it. -->
      <q-menu
        v-model="isShowingArguments"
        :class="$style.arguments"
        no-parent-event
        :offset="[0, 4]"
      >
        <div class="q-pa-sm">
          <div class="items-center no-wrap q-mb-sm row">
            <common-text class="monospace-sm" variant="th">{{ actionPath }}</common-text>
            <q-space />
            <q-btn
              :color="button.confirm ? 'primary' : 'warning'"
              dense
              flat
              :icon="icons.confirmDialog"
              round
              size="sm"
              @click="button.confirm = !button.confirm"
            >
              <q-tooltip :class="button.confirm ? 'bg-primary text-white' : 'bg-warning text-dark'">
                {{ button.confirm ? 'Confirm Dialog Enabled' : 'Confirm Dialog Disabled' }}
              </q-tooltip>
            </q-btn>
            <!-- Locked runs with one less look at the arguments, which is the riskier state,
            so it is the one that carries the warning color. -->
            <q-btn
              :color="button.locked ? 'warning' : 'primary'"
              dense
              flat
              :icon="button.locked ? icons.locked : icons.unlocked"
              round
              size="sm"
              @click="toggleLock"
            >
              <q-tooltip :class="button.locked ? 'bg-warning text-dark' : 'bg-primary text-white'">
                {{ button.locked ? 'Arguments Locked' : 'Arguments Unlocked' }}
              </q-tooltip>
            </q-btn>
          </div>
          <q-card bordered class="q-mb-sm q-pa-sm" flat>
            <schema-form :form />
          </q-card>
          <!-- The label says what backing out means right now, closing the popup at rest and
          aborting the action once one is in flight. -->
          <schema-form-controls
            :cancel-label="running != null ? 'Abort' : 'Cancel'"
            :execute-label="button.confirm ? 'Execute ...' : 'Execute'"
            :form
            @cancel="onCancel"
          />
        </div>
      </q-menu>
    </q-btn>
    <q-btn
      :class="[$style.more, isShowingMenu && $style.moreOpen]"
      dense
      flat
      :icon="icons.more"
      size="7px"
      @click.stop="menu?.show($event)"
    />
    <q-menu ref="menu" context-menu @hide="isShowingMenu = false" @show="isShowingMenu = true">
      <q-list bordered dense>
        <q-item v-close-popup clickable dense @click="isShowingSettings = true">
          <q-item-section avatar>
            <q-icon :name="icons.settings" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Configure ...</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-close-popup clickable dense :disable="!takesArguments" @click="showArguments()">
          <q-item-section avatar>
            <q-icon :name="icons.edit" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Arguments ...</q-item-label>
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
        <q-item v-close-popup clickable dense @click="emit('addBefore')">
          <q-item-section avatar>
            <q-icon :name="icons.add" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Add Button Before</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-close-popup clickable dense @click="emit('addAfter')">
          <q-item-section avatar>
            <q-icon :name="icons.add" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Add Button After</q-item-label>
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
          <workspace-widget-control-settings :button />
        </div>
        <q-separator />
        <q-btn
          class="full-width"
          color="primary"
          dense
          flat
          label="Done"
          no-caps
          @click="isShowingSettings = false"
        />
      </q-card>
    </q-dialog>
    <q-dialog :model-value="answerConfirm != null" @update:model-value="confirmWith(false)">
      <q-card bordered :class="$style.confirm" flat>
        <div class="q-pa-md">
          <common-text class="q-mb-xs" variant="title1">Execute {{ button.action }}?</common-text>
          <common-text variant="description">
            This executes {{ button.action }} on {{ resolvedAddress }}.
          </common-text>
        </div>
        <template v-if="confirmingArguments != null">
          <q-separator />
          <!-- eslint-disable-next-line vue/no-v-html -->
          <pre :class="$style.confirmArguments"><code v-html="confirmingArguments" /></pre>
        </template>
        <q-separator />
        <div class="q-col-gutter-sm q-pa-sm row">
          <div class="col">
            <q-btn
              class="full-width"
              color="primary"
              dense
              label="Execute"
              no-caps
              unelevated
              @click="confirmWith(true)"
            />
          </div>
          <div class="col">
            <q-btn
              class="full-width"
              dense
              flat
              label="Cancel"
              no-caps
              @click="confirmWith(false)"
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

// The dots wait just under the button rather than beside or over it so a bar of buttons is a bar
// of buttons and arranging one costs no room until it is reached for. Kept quiet even then,
// hinted while the button is hovered and only fully there when reached for themselves.
.more {
  position: absolute;
  top: calc(100% + 2px);
  left: 50%;
  z-index: 1;
  min-height: 0;
  padding: 0 3px;
  opacity: 0;
  transform: translateX(-50%);
  transition: opacity 0.15s;
}

.root:hover .more,
.more:focus {
  opacity: 0.5;
}

.root .more:hover,
.more:focus {
  opacity: 1;
}

.root .more.moreOpen {
  opacity: 1;
}

/* Tucked against the label so the pair reads as one word, without the room a full character of
padding would take. */
.asks {
  margin-right: -3px;
  margin-left: 1px;
  opacity: 0.8;
}

/* Bordered the way the menus are since on a dark surface a shadow alone does not say where the
popup ends. */
.arguments {
  max-width: 420px;
  width: 100%;
  border: 1px solid #0000001f;
}

:global(.dark) .arguments {
  border-color: #ffffff47;
}

.settings {
  max-width: 400px;
  width: 100%;
}

// The same shape the configuration block wears, capped so long arguments scroll in place.
.confirmArguments {
  overflow: auto;
  max-height: 240px;
  margin: 0;
  padding: 8px 16px;
  font-size: 12px;
  line-height: 1.5;
}

.confirm {
  max-width: 360px;
  width: 100%;
}
</style>
