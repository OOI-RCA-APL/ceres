<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { startCase } from 'lodash-es'
import { nextTick } from 'vue'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { isError } from '@/api/shared'
import { semanticColor } from '@/colors'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { useNotify } from '@/notify'
import { isEmptyObjectSchema, useSchemaForm } from '@/schema-form'
import { displayDuration, useTime } from '@/time'
import { afterMenuCloses, deepClone, highlight } from '@/utilities'
import type { Plain } from '@/utilities'
import { useWorkspace } from '@/workspace'
import type { ButtonAction } from '@/workspace'

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
const time = useTime()
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
  () => resolvedAddress != null && access.canOperate(resolvedAddress.toString()),
)

// A fresh button holds no action yet so pressing it opens the settings that give it one.
const isConfigured = $computed(() => button.address != null && button.action != null)

const color = $computed(() => (button.color == null ? 'neutral' : semanticColor(button.color)))

const variant = $computed(() => {
  if (button.styling === 'flat') {
    return 'ghost'
  }
  if (button.styling === 'outlined') {
    return 'outline'
  }

  return 'solid'
})

let isRunning = $ref(false)
let isShowingArguments = $ref(false)
let isShowingSettings = $ref(false)
let isShowingMenu = $ref(false)

// The arguments are edited on a copy of what the button holds so a popup opened and dismissed
// leaves the button exactly as it was found. They are kept on submitting or on locking, which are
// the two ways a user says the arguments are the ones they meant.
let draft: unknown = $ref({})

const held = {
  value: () => draft as Plain,
  onUpdate: (value: unknown) => {
    draft = value
  },
}

const form = useSchemaForm({
  ...held,
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
    (button.address != null ? String(button.address) : 'Button'),
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

It carries the running time and an "Abort" for as long as the action runs, then settles into how
the run ended and leaves on the timeout that severity earns.
*/
function createRunToast(controller: AbortController) {
  const startedAt = time.now.valueOf()
  const elapsed = () => displayDuration((time.now.valueOf() - startedAt) / 1000, { short: true })

  // No icon while it runs. A toast cannot spin one, and a still ring reads as a progress bar
  // stuck at the same place, against a run whose length is not known anyway.
  const toast = notify.open({
    title: actionPath,
    description: elapsed(),
    color: 'primary',
    actions: [{ label: 'Abort', color: 'neutral', onClick: () => controller.abort() }],
  })

  const ticker = setInterval(() => toast.update({ description: elapsed() }), 1000)

  function settle(color: 'success' | 'neutral' | 'error', title: string, duration: number) {
    clearInterval(ticker)
    toast.update({
      title,
      description: elapsed(),
      color,
      icon: color === 'error' ? icons.cancel : icons.confirm,
      actions: [],
      duration,
    })
  }

  return {
    succeeded: () => settle('success', `Action "${button.action}" succeeded.`, 3000),
    canceled: () => settle('neutral', `Action "${button.action}" was canceled.`, 3000),
    failed: (detail: string) =>
      settle('error', `Action "${button.action}" failed. ${detail}`, 8000),
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
    const result = await engine.components.call(
      resolvedAddress,
      button.action,
      values as Record<string, unknown>,
      { signal: controller.signal },
    )

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

/** Open the arguments from a menu, once that menu has finished closing.

A menu hands focus back to its own trigger as it goes, and the popup reads focus landing outside
itself as a click away, so opening any sooner closes it in the same breath.
*/
function showArgumentsFromMenu() {
  afterMenuCloses(() => void showArguments())
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

const menuItems = $computed<DropdownMenuItem[][]>(() => [
  [
    { label: 'Configure ...', icon: icons.settings, onSelect: () => (isShowingSettings = true) },
    {
      label: 'Arguments ...',
      icon: icons.edit,
      disabled: !takesArguments,
      onSelect: showArgumentsFromMenu,
    },
    { label: 'Duplicate', icon: icons.duplicate, onSelect: () => emit('duplicate') },
    { label: 'Add Button Before', icon: icons.add, onSelect: () => emit('addBefore') },
    { label: 'Add Button After', icon: icons.add, onSelect: () => emit('addAfter') },
  ],
  [{ label: 'Delete', icon: icons.delete, onSelect: () => emit('remove') }],
])

const tooltip = $computed(() => {
  if (isRunning) {
    return 'Press to Abort'
  }
  if (!isConfigured) {
    return 'Button action is not configured. Press to configure.'
  }
  if (action == null) {
    return `Button action ${resolvedAddress}::action::${button.action} not found.`
  }

  return button.tooltip ?? null
})
</script>

<template>
  <!-- A button carries its own menu so the press that opens it must not reach the widget's, which
  is hung off the card around everything here. -->
  <c-context-menu :items="menuItems" @update:open="(value: boolean) => (isShowingMenu = value)">
    <!-- Named, since the bar around this one is a group too and the dots answer only to their
    own button being pointed at. -->
    <div class="group/control relative inline-flex" @contextmenu.stop>
      <c-popover v-model:open="isShowingArguments" :ui="{ content: 'w-[420px] max-w-[90vw]' }">
        <c-tooltip :disabled="tooltip == null" :text="tooltip ?? ''">
          <c-button
            :color="color"
            :disabled="isConfigured && (!canOperate || action == null)"
            size="sm"
            :variant="variant"
            @click="onPress"
          >
            <!-- Drawn beside the label rather than through the button's own loading state, which
            swallows the press that is the abort. -->
            <c-icon v-if="isRunning" class="animate-spin" :name="icons.loading" size="14" />
            <span @pointerenter="isLabelHovered = true" @pointerleave="isLabelHovered = false">
              <c-inline-name-edit
                :claim="isEditingLabel"
                :editing="isLabelOffered"
                :name="named"
                @rename="renameButton"
                @update:editing="(value: boolean) => (isEditingLabel = value)"
              />
            </span>
            <!-- The chevron is how a control says it asks something before it acts, whether what
            it opens is the arguments or the question of whether to go ahead at all. -->
            <c-icon
              v-if="opensDialog"
              class="-mr-1 opacity-80"
              :name="icons.chevronDown"
              size="14"
            />
          </c-button>
        </c-tooltip>
        <!-- The arguments are asked for where the button is rather than in the middle of the
        screen, so the thing being run stays in view beside the form that runs it. -->
        <template #content>
          <div class="p-2">
            <div class="mb-2 flex flex-nowrap items-center gap-1">
              <c-text class="grow" variant="mono-sm">{{ actionPath }}</c-text>
              <c-tooltip
                :text="button.confirm ? 'Confirm Dialog Enabled' : 'Confirm Dialog Disabled'"
              >
                <c-button
                  :color="button.confirm ? 'primary' : 'warning'"
                  :icon="icons.confirmDialog"
                  size="xs"
                  variant="ghost"
                  @click="button.confirm = !button.confirm"
                />
              </c-tooltip>
              <!-- Locked runs with one less look at the arguments, which is the riskier state,
              so it is the one that carries the warning color. -->
              <c-tooltip :text="button.locked ? 'Arguments Locked' : 'Arguments Unlocked'">
                <c-button
                  :color="button.locked ? 'warning' : 'primary'"
                  :icon="button.locked ? icons.locked : icons.unlocked"
                  size="xs"
                  variant="ghost"
                  @click="toggleLock"
                />
              </c-tooltip>
            </div>
            <div class="border-default mb-2 rounded-md border p-2">
              <c-schema-form :form />
            </div>
            <!-- The label says what backing out means right now, closing the popup at rest and
            aborting the action once one is in flight. -->
            <c-schema-form-controls
              :cancel-label="running != null ? 'Abort' : 'Cancel'"
              :execute-label="button.confirm ? 'Execute ...' : 'Execute'"
              :form
              @cancel="onCancel"
            />
          </div>
        </template>
      </c-popover>
      <c-dropdown-menu :items="menuItems">
        <!-- The dots wait just under the button rather than beside or over it, so a bar of
        buttons is a bar of buttons and arranging one costs no room until it is reached for. -->
        <c-button
          :class="[
            'absolute top-[calc(100%+2px)] left-1/2 z-1 min-h-0 -translate-x-1/2 px-[3px]',
            'opacity-0 transition-opacity duration-150',
            'group-hover/control:opacity-50 hover:opacity-100! focus:opacity-100!',
            isShowingMenu && 'opacity-100!',
          ]"
          :icon="icons.more"
          size="xs"
          variant="link"
        />
      </c-dropdown-menu>
    </div>
  </c-context-menu>
  <c-modal
    v-model:open="isShowingSettings"
    title="Button"
    :ui="{ content: 'w-[400px] max-w-[90vw]' }"
  >
    <template #body>
      <c-workspace-widget-control-settings :button />
    </template>
    <template #footer>
      <c-button
        block
        color="primary"
        label="Done"
        variant="ghost"
        @click="isShowingSettings = false"
      />
    </template>
  </c-modal>
  <c-modal
    :open="answerConfirm != null"
    :title="`Execute ${button.action}?`"
    :ui="{ content: 'w-[360px] max-w-[90vw]' }"
    @update:open="confirmWith(false)"
  >
    <template #body>
      <c-text variant="description">
        This executes {{ button.action }} on {{ resolvedAddress }}.
      </c-text>
      <pre
        v-if="confirmingArguments != null"
        class="m-0 mt-2 max-h-60 overflow-auto text-[12px] leading-normal"
      ><!-- eslint-disable-line vue/no-v-html --><code v-html="confirmingArguments" /></pre>
    </template>
    <template #footer>
      <div class="grid w-full grid-cols-2 gap-2">
        <c-button block color="primary" label="Execute" @click="confirmWith(true)" />
        <c-button block label="Cancel" variant="ghost" @click="confirmWith(false)" />
      </div>
    </template>
  </c-modal>
</template>
