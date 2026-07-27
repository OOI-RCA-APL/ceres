<script lang="ts" setup>
import { until } from '@vueuse/core'
import { upperFirst } from 'lodash-es'
import { useDialogPluginComponent } from 'quasar'
import { reactive, computed, nextTick } from 'vue'

import { useAccess } from '@/api/access'
import { useAuth } from '@/api/auth'
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'
import { WorkspaceData } from '@/workspace'

const { workspaceId, data, action } = defineProps<
  | {
      workspaceId: string
      action: 'view'
      data?: null
    }
  | {
      workspaceId: string
      action: 'duplicate'
      data?: WorkspaceData
    }
>()

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

const access = useAccess()
const auth = useAuth()
const engine = useEngine()
const navigation = useNavigation()
const notify = useNotify()
const validate = useValidate()

const key = Math.random()
const query = reactive(
  useQuery({
    queryKey: computed(() => ['workspace-dialog', workspaceId, auth.user?.id, key]),
    queryFn: async () => {
      await auth.refresh()
      return { workspace: await engine.workspaces.get(workspaceId) }
    },
  })
)

const workspace = $computed(() => query.data?.workspace ?? null)
const isPrivate = $computed(() => workspace?.owner_id != null)
const isEnginePlaced = $computed(() => workspace?.scope.isEngine === true)

// A workspace inherits its permissions from its placement, except a private one, which belongs to
// its owner alone. Engine-level manage comes from an all-target grant, which the console models as
// manage on every component rather than as a level on the root itself.
const canManage = $computed(() => {
  if (action === 'duplicate') {
    return true
  }
  if (workspace == null) {
    return false
  }
  if (isPrivate) {
    return workspace.owner_id === auth.user?.id
  }
  if (isEnginePlaced) {
    return auth.user?.admin === true
  }

  return access.canManage(workspace.scope.toString())
})

const form = useForm({
  editing: action === 'duplicate',
  data: {
    name: 'Workspace',
  },
  validators: {
    name: validate.isNotBlank(),
  },
  onSubmit: async (values) => {
    if (action === 'view') {
      await engine.workspaces.update(workspaceId, values)
      notify.success('Workspace settings updated successfully.')
    } else if (action === 'duplicate' && workspaceId) {
      // A duplicate starts private, so an arrangement can be tried out before anyone else sees it.
      const copy = await engine.workspaces.create({
        ...values,
        scope: workspace?.scope,
        owner_id: auth.user?.id,
        data: data ?? workspace?.data ?? {},
      })
      notify.success('Workspace duplicated successfully.')
      navigation.go(`/workspaces/${copy.id}`)
    }

    onDialogOK()
  },
})

nextTick(async () => {
  await until(() => query.isFetched).toBe(true)
  if (workspace != null) {
    form.load(workspace)
    if (action === 'duplicate') {
      form.data.name = `${workspace.name} (Copy)`
    }
  }
})
</script>

<template>
  <q-dialog ref="dialogRef" :persistent="form.editable" @hide="onDialogHide">
    <q-card v-if="auth.user != null" bordered class="q-dialog-plugin" :class="$style.card" flat>
      <div class="q-px-md row">
        <common-text class="q-mb-sm q-mt-sm" element="h2" variant="title1">
          {{ action === 'view' ? 'Workspace Settings' : 'Duplicate Workspace' }}
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
            <div class="q-mb-sm text-grey-6">
              <template v-if="isPrivate">
                <q-icon class="q-mr-xs" :name="icons.privateWorkspace" />
                This workspace is private to you. Nobody else can see it, whatever access they have
                to <span class="monospace-xs">{{ workspace?.scope }}</span
                >.
              </template>
              <template v-else-if="isEnginePlaced">
                This workspace is not bound to a component, so anyone signed in can see it and
                anyone with engine-wide manage access can edit it.
              </template>
              <template v-else>
                Access to this workspace follows the
                <span class="monospace-xs">{{ workspace?.scope }}</span> component, so anyone who
                can view that component can see it, and anyone who can manage it can edit it.
              </template>
            </div>
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
              :label="action !== 'view' ? upperFirst(action) : 'Save'"
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
