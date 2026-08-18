<script lang="ts"></script>

<script lang="ts" setup>
import { until } from '@vueuse/core'
import { computed, nextTick, reactive } from 'vue'

import { useAccess } from '@/api/access'
import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { useDialogs } from '@/dialogs'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { usePreferences } from '@/preferences'
import { useValidate } from '@/validate'
import type { Workspace, WorkspaceData } from '@/workspace'
export type WorkspaceDialogProps =
  | {
      workspaceId: string
      action: 'view'
      data?: null
      scope?: null
      isPrivate?: null
    }
  | {
      workspaceId: string
      action: 'duplicate'
      data?: WorkspaceData
      scope?: null
      isPrivate?: null
    }
  | {
      workspaceId?: null
      action: 'create'
      data?: null
      /** Placement the new workspace sits on, defaulting to the engine root. */
      scope?: string

      /** Which kind to start on, for a caller that already knows. Without one the form opens on
      whichever kind was made last.
      */
      isPrivate?: boolean | null
    }

const {
  workspaceId,
  data = null,
  action,
  scope = null,
  isPrivate: presetIsPrivate = null,
} = defineProps<WorkspaceDialogProps>()

/** Closes with the created workspace, `true` for saved settings, or `false` for a cancel. */
const emit = defineEmits<{ close: [Workspace | boolean] }>()

const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const engine = useEngine()
const notify = useNotify()
const preferences = usePreferences()
const validate = useValidate()

const key = Math.random()
const query = reactive(
  useQuery({
    queryKey: computed(() => ['workspace-dialog', workspaceId ?? null, auth.user?.id, key]),
    queryFn: async () => {
      await auth.refresh()
      return { workspace: workspaceId != null ? await engine.workspaces.get(workspaceId) : null }
    },
  }),
)

const workspace = $computed(() => query.data?.workspace ?? null)

// Everything the dialog explains follows from where the workspace sits and whether it is owned.
// A workspace being created has no row to read those from yet so they come from the placement
// passed in and from the choice the form is currently showing.
const placement = $computed(() =>
  action === 'create' ? new Address(scope ?? engineRoot) : (workspace?.scope ?? null),
)

// A shared workspace appears for everyone who can see its placement so creating one takes manage
// there. A private one is visible to nobody else and takes only the view access needed to be
// looking at the placement at all.
const canShare = $computed(() => placement != null && access.canManage(placement.toString()))

const titles = {
  view: 'Workspace Settings',
  duplicate: 'Duplicate Workspace',
  create: 'Create Workspace',
} as const

const submitLabels = {
  view: 'Save',
  duplicate: 'Duplicate',
  create: 'Create',
} as const

const form = useForm({
  editing: action !== 'view',
  data: {
    name: 'Workspace',
    // A duplicate starts private so an arrangement can be tried out before anyone else sees it,
    // and can still be shared from the same form. A new one starts on whichever kind was made
    // last, or on whichever kind the caller asked for.
    isPrivate: true,
    // Whether this is one of the workspaces a new user lands on. Only meaningful for a shared
    // workspace placed on the engine root, which the home page draws its defaults from.
    showWhenLoggedOut: false,
  },
  validators: {
    name: validate.isNotBlank(),
  },
  onSubmit: async (values) => {
    if (action === 'view') {
      // Changing visibility moves this workspace rather than copying it, so publishing shows
      // it to everyone on the placement and taking it private removes it for them. A private
      // workspace needs an owner, so without one the change would silently publish instead.
      const wasPrivate = workspace?.owner_id != null
      const owner = values.isPrivate ? (auth.user?.id ?? null) : null
      const changingVisibility =
        values.isPrivate !== wasPrivate && (!values.isPrivate || owner != null)

      // Taking a shared workspace private removes it for everyone else, so it takes the same
      // warning the drag path shows.
      if (changingVisibility && values.isPrivate) {
        const confirmed = await new Promise<boolean>((resolve) => {
          dialogs
            .confirm({
              title: 'Make Workspace Private',
              message: `"${values.name}" becomes private to you.`,
              note:
                'Anyone else who can see it loses access, along with any unsaved changes they ' +
                'are holding against it.',
            })
            .onOk(() => resolve(true))
            .onCancel(() => resolve(false))
        })
        if (!confirmed) {
          return
        }
      }

      await engine.workspaces.update(workspaceId as string, {
        name: values.name,
        ...(changingVisibility ? { owner_id: owner } : {}),
        ...(canMarkForHome ? { show_when_logged_out: values.showWhenLoggedOut } : {}),
      })
      notify.success('Workspace settings updated successfully.')
      emit('close', true)
      return
    }

    const created = await engine.workspaces.create({
      name: values.name,
      scope: placement ?? undefined,
      owner_id: values.isPrivate ? auth.user?.id : null,
      data: action === 'duplicate' ? (data ?? workspace?.data ?? undefined) : undefined,
    })

    // Only a deliberate choice is remembered. Duplicating is always private, and a user without
    // manage has no choice to make so neither says anything about what they prefer.
    if (action === 'create' && canShare) {
      preferences.wasLastWorkspacePrivate = values.isPrivate
    }

    notify.success(
      action === 'duplicate'
        ? 'Workspace duplicated successfully.'
        : 'Workspace created successfully.',
    )

    // Handed back so the caller can place it. Where it belongs depends on where it was made, and a
    // copy goes beside its original, neither of which the dialog is in a position to know.
    emit('close', created)
  },
})

// Creating and duplicating both explain the workspace the form is about to make, and an edit in
// the settings view explains the choice it is holding. Only a read-only view describes the
// workspace exactly as it stands.
const isPrivate = $computed(() =>
  action === 'view' && !form.editable ? workspace?.owner_id != null : form.data.isPrivate,
)

// Named rather than switched so the choice reads as two kinds of workspace. Publishing takes
// manage on the placement, so without it the shared kind is not offered.
const visibilityOptions = $computed(() => [
  { label: 'Shared', value: false, icon: icons.workspace, disabled: !canShare },
  { label: 'Private', value: true, icon: icons.privateWorkspace },
])

// Read from the stored workspace rather than the form so an unsaved visibility choice cannot
// take the caller's own controls away mid-edit.
const canManage = $computed(() => {
  if (action !== 'view') {
    return true
  }
  if (workspace == null) {
    return false
  }
  if (workspace.owner_id != null) {
    return workspace.owner_id === auth.user?.id
  }

  return canShare
})

// The home page's default set. It only applies to a shared workspace on the engine root, and it
// decides what everyone lands on so it takes manage there. A private workspace can never carry
// it because nobody else can see one.
const canMarkForHome = $computed(
  () => action === 'view' && !isPrivate && placement?.isEngine === true && canShare,
)

void nextTick(async () => {
  await until(() => query.isFetched).toBe(true)
  if (action === 'create') {
    // A caller that already knows which kind it wants says so. Without manage there is no choice
    // to make since sharing is not available.
    if (!canShare) {
      form.data.isPrivate = true
    } else {
      form.data.isPrivate = presetIsPrivate ?? preferences.wasLastWorkspacePrivate
    }

    return
  }
  if (workspace != null) {
    // Mapped in by hand because the form names these fields differently from the wire, and
    // loading them seeds the stored copy an edit resets to.
    form.load({
      ...workspace,
      isPrivate: workspace.owner_id != null,
      showWhenLoggedOut: workspace.show_when_logged_out,
    })
    if (action === 'duplicate') {
      form.data.name = `${workspace.name} (Copy)`
      form.data.isPrivate = true
    }
  }
})
</script>

<template>
  <c-modal
    :dismissible="!form.editable"
    :title="titles[action]"
    :ui="{ content: 'w-[560px] max-w-[95vw]' }"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <div v-if="query.isLoading" class="flex justify-center p-4">
        <c-page-spinner />
      </div>
      <c-text v-else-if="query.error" element="p" variant="body1">
        An error occurred while loading the workspace. {{ query.error }}
      </c-text>
      <form v-else @submit.prevent="form.submit()">
        <c-input
          v-model="form.data.name"
          autofocus
          class="mb-2 w-full"
          :disabled="form.readonly"
          placeholder="Workspace Name"
        />
        <c-select
          v-if="action === 'view' || canShare"
          v-model="form.data.isPrivate"
          class="mb-2 w-full"
          :disabled="form.readonly"
          :icon="form.data.isPrivate ? icons.privateWorkspace : icons.workspace"
          :items="visibilityOptions"
          label-key="label"
          value-key="value"
        />
        <c-text class="mb-2 block" variant="description">
          <template v-if="isPrivate">
            <c-icon class="mr-1 align-text-bottom" :name="icons.privateWorkspace" size="14" />
            This workspace is private to you.
          </template>
          <template v-else-if="placement?.isEngine">
            Anyone signed in can see this workspace.
          </template>
          <template v-else>
            Access follows the <c-text variant="mono-xs">{{ placement }}</c-text> component.
          </template>
        </c-text>
        <c-text v-if="action === 'create' && !canShare" class="block" variant="description">
          Sharing requires manage access.
        </c-text>
        <template v-if="canMarkForHome">
          <c-separator class="my-2" />
          <c-checkbox
            v-model="form.data.showWhenLoggedOut"
            :disabled="form.readonly"
            label="Show On Home"
          />
          <c-text class="mt-2 block" variant="description">
            Workspaces shown here are what a new user sees when they first sign in.
          </c-text>
        </template>
      </form>
    </template>
    <template v-if="canManage && !query.isLoading" #footer>
      <div class="flex w-full gap-2">
        <c-button
          v-if="action === 'view' && form.readonly"
          block
          class="flex-1"
          color="primary"
          :icon="icons.edit"
          label="Edit"
          @click="form.edit()"
        />
        <c-button
          v-if="action === 'view' && form.editable"
          block
          class="flex-1"
          color="neutral"
          :icon="icons.cancel"
          label="Cancel"
          variant="soft"
          @click="form.discard()"
        />
        <c-button
          v-if="form.editable"
          block
          class="flex-1"
          color="primary"
          :disabled="form.validation !== 'valid'"
          :icon="icons.confirm"
          :label="submitLabels[action]"
          :loading="form.state === 'submitting'"
          @click="form.submit()"
        />
      </div>
    </template>
  </c-modal>
</template>
