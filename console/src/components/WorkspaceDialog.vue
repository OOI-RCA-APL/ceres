<script lang="ts" setup>
import { until } from '@vueuse/core'
import { useDialogPluginComponent } from 'quasar'
import { reactive, computed, nextTick } from 'vue'

import { useAccess } from '@/api/access'
import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { usePreferences } from '@/preferences'
import { useValidate } from '@/validate'
import { WorkspaceData } from '@/workspace'

const {
  workspaceId = null,
  data = null,
  action,
  scope = null,
} = defineProps<
  | {
      workspaceId: string
      action: 'view'
      data?: null
      scope?: null
    }
  | {
      workspaceId: string
      action: 'duplicate'
      data?: WorkspaceData
      scope?: null
    }
  | {
      workspaceId?: null
      action: 'create'
      data?: null
      /** Placement the new workspace sits on, defaulting to the engine root. */
      scope?: string
    }
>()

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

const access = useAccess()
const auth = useAuth()
const engine = useEngine()
const navigation = useNavigation()
const notify = useNotify()
const preferences = usePreferences()
const validate = useValidate()

const key = Math.random()
const query = reactive(
  useQuery({
    queryKey: computed(() => ['workspace-dialog', workspaceId, auth.user?.id, key]),
    queryFn: async () => {
      await auth.refresh()
      return { workspace: workspaceId != null ? await engine.workspaces.get(workspaceId) : null }
    },
  })
)

const workspace = $computed(() => query.data?.workspace ?? null)

// Everything the dialog explains follows from where the workspace sits and whether it is owned.
// A workspace being created has no row to read those from yet, so they come from the placement
// passed in and from the choice the form is currently showing.
const placement = $computed(() =>
  action === 'create' ? new Address(scope ?? engineRoot) : workspace?.scope ?? null
)

// A shared workspace appears for everyone who can see its placement, so creating one takes manage
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
    // A duplicate starts private, so an arrangement can be tried out before anyone else sees it.
    // A new workspace starts shared wherever that is available, which is what creating one used
    // to always do.
    isPrivate: true,
    // Whether this is one of the workspaces a new user lands on. Only meaningful for a shared
    // workspace placed on the engine root, which is what the home page draws its defaults from.
    showWhenLoggedOut: false,
  },
  validators: {
    name: validate.isNotBlank(),
  },
  onSubmit: async (values) => {
    if (action === 'view') {
      await engine.workspaces.update(workspaceId, {
        name: values.name,
        ...(canMarkForHome ? { show_when_logged_out: values.showWhenLoggedOut } : {}),
      })
      notify.success('Workspace settings updated successfully.')
      onDialogOK()
      return
    }

    const created = await engine.workspaces.create({
      name: values.name,
      scope: placement ?? undefined,
      owner_id: values.isPrivate ? auth.user?.id : null,
      data: action === 'duplicate' ? data ?? workspace?.data ?? {} : undefined,
    })

    // Only a deliberate choice is remembered. Duplicating is always private, and a user without
    // manage has no choice to make, so neither says anything about what they prefer.
    if (action === 'create' && canShare) {
      preferences.wasLastWorkspacePrivate = values.isPrivate
    }

    if (action === 'duplicate') {
      // A copy opens on its own page. Its callers duplicate from wherever they happen to be, so
      // the dialog takes them to the copy rather than leaving them on the original.
      notify.success('Workspace duplicated successfully.')
      await navigation.go(`/workspaces/${created.id}`)
    } else {
      // A new workspace is handed back so the caller can place it, since where it belongs depends
      // on whether it was created from the sidebar or from a component's tab strip.
      notify.success('Workspace created successfully.')
    }

    onDialogOK(created)
  },
})

// Creating and duplicating both explain the workspace the form is about to make, which the form's
// own choice decides. Only the settings view describes a workspace that already exists.
const isPrivate = $computed(() =>
  action === 'view' ? workspace?.owner_id != null : form.data.isPrivate
)

// Named rather than switched, so the choice reads as two kinds of workspace instead of a setting
// that happens to be off.
const visibilityOptions = [
  { label: 'Shared', value: false, icon: icons.workspace },
  { label: 'Private', value: true, icon: icons.privateWorkspace },
]

const canManage = $computed(() => {
  if (action !== 'view') {
    return true
  }
  if (workspace == null) {
    return false
  }
  if (isPrivate) {
    return workspace.owner_id === auth.user?.id
  }

  return canShare
})

// The home page's default set. It only applies to a shared workspace on the engine root, and it
// decides what everyone lands on, so it takes manage there. A private workspace can never carry
// it, because nobody else can see one.
const canMarkForHome = $computed(
  () => action === 'view' && !isPrivate && placement?.isEngine === true && canShare
)

nextTick(async () => {
  await until(() => query.isFetched).toBe(true)
  if (action === 'create') {
    form.data.isPrivate = canShare ? preferences.wasLastWorkspacePrivate : true
    return
  }
  if (workspace != null) {
    form.load(workspace)
    form.data.showWhenLoggedOut = workspace.show_when_logged_out
    if (action === 'duplicate') {
      form.data.name = `${workspace.name} (Copy)`
      form.data.isPrivate = true
    }
  }
})
</script>

<template>
  <q-dialog ref="dialogRef" :persistent="form.editable" @hide="onDialogHide">
    <q-card v-if="auth.user != null" bordered class="q-dialog-plugin" :class="$style.card" flat>
      <div class="q-px-md row">
        <common-text class="q-mb-sm q-mt-sm" element="h2" variant="title1">
          {{ titles[action] }}
        </common-text>
        <q-space />
        <div class="items-center row">
          <q-btn flat :icon="icons.close" round size="10px" @click="onDialogCancel" />
        </div>
      </div>
      <div v-if="query.isLoading" class="justify-center q-pa-md row">
        <q-spinner-orbit color="primary" size="25px" />
      </div>
      <template v-else>
        <q-separator />
        <q-form :ref="form.bind" class="q-py-md" @submit="form.submit">
          <div v-if="query.error" class="q-pt-none q-px-md">
            <common-text element="p" variant="body1">
              An error occurred while loading the workspace. {{ query.error }}
            </common-text>
          </div>
          <div v-else class="q-pt-none q-px-md">
            <q-input
              v-model="form.data.name"
              autofocus
              class="q-mb-md"
              color="primary"
              dense
              label="Workspace Name"
              lazy-rules
              no-error-icon
              outlined
              :readonly="form.readonly"
            />
            <q-select
              v-if="action === 'create' && canShare"
              v-model="form.data.isPrivate"
              class="q-mb-md"
              color="primary"
              dense
              emit-value
              label="Visibility"
              map-options
              :options="visibilityOptions"
              options-dense
              outlined
            >
              <template #prepend>
                <q-icon
                  :name="form.data.isPrivate ? icons.privateWorkspace : icons.workspace"
                  size="20px"
                />
              </template>
              <template #option="scope">
                <q-item v-bind="scope.itemProps" dense>
                  <q-item-section avatar>
                    <q-icon :name="scope.opt.icon" size="20px" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ scope.opt.label }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
            <div class="q-mb-sm text-grey-6">
              <template v-if="isPrivate && placement?.isEngine">
                <q-icon class="q-mr-xs" :name="icons.privateWorkspace" />
                This workspace is private to you. Nobody else can see it.
              </template>
              <template v-else-if="isPrivate">
                <q-icon class="q-mr-xs" :name="icons.privateWorkspace" />
                This workspace is private to you. Nobody else can see it, whatever access they have
                to <span class="monospace-xs">{{ placement }}</span
                >.
              </template>
              <template v-else-if="placement?.isEngine">
                This workspace is not bound to a component, so anyone signed in can see it and
                anyone with engine-wide manage access can edit it.
              </template>
              <template v-else>
                Access to this workspace follows the
                <span class="monospace-xs">{{ placement }}</span> component, so anyone who can view
                that component can see it, and anyone who can manage it can edit it.
              </template>
            </div>
            <div v-if="action === 'create' && !canShare" class="text-grey-6">
              Sharing it with everyone who can see
              <span class="monospace-xs">{{ placement }}</span> requires manage access.
            </div>
            <template v-if="canMarkForHome">
              <q-separator class="q-mb-sm q-mt-sm" />
              <q-toggle
                v-model="form.data.showWhenLoggedOut"
                dense
                :disable="form.readonly"
                label="Show on the home page"
              />
              <div class="q-mt-xs text-grey-6">
                Workspaces shown here are what a new user sees when they first sign in.
              </div>
            </template>
          </div>
        </q-form>
        <div v-if="canManage" class="q-col-gutter-x-sm q-pb-md q-px-md row">
          <div v-if="action === 'view' && form.readonly" class="col">
            <q-btn
              class="full-width"
              color="primary"
              :icon="icons.edit"
              label="Edit"
              unelevated
              @click="form.edit()"
            />
          </div>
          <div v-if="action === 'view' && form.editable" class="col">
            <q-btn
              class="full-width"
              color="grey-8"
              :icon="icons.cancel"
              label="Cancel"
              unelevated
              @click="form.discard()"
            />
          </div>
          <div v-if="form.editable" class="col">
            <q-btn
              class="full-width"
              color="primary"
              :disable="form.validation !== 'valid'"
              :icon="icons.confirm"
              :label="submitLabels[action]"
              :loading="form.state === 'submitting'"
              type="submit"
              unelevated
              @click="form.submit()"
            />
          </div>
        </div>
      </template>
    </q-card>
  </q-dialog>
</template>

<style lang="scss" module>
.card {
  max-width: 560px;
  width: 560px;
}
</style>
