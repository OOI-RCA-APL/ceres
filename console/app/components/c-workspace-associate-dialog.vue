<script lang="ts"></script>

<script lang="ts" setup>
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import icons from '@/icons'
import { isWorkspaceWritable, type Workspace } from '@/workspace'
import { pinWidgetAddresses, widgetsOutside } from '@/workspace/association'

export type WorkspaceAssociateDialogProps = {
  /** The workspace to place elsewhere. Without one, the dialog asks which of `candidates`. */
  workspace?: Workspace | null
  candidates?: Workspace[]
  /** Where it goes, already chosen by a drop or by the page it was asked from. */
  destination?: string | null
}

export type WorkspaceAssociation = {
  workspace: Workspace
  destination: string
  /** Whether the workspace itself changes placement or a copy is made there. */
  mode: 'change' | 'copy'
  /** For a copy, whether it is the caller's own. */
  isPrivate: boolean
}

const {
  workspace: given = null,
  candidates = [],
  destination: presetDestination = null,
} = defineProps<WorkspaceAssociateDialogProps>()

/** Closes with the chosen association, or `false` for a cancel. */
const emit = defineEmits<{ close: [WorkspaceAssociation | false] }>()

const access = useAccess()
const auth = useAuth()

let chosenId = $ref<string | null>(given?.id ?? null)
const workspace = $computed(
  () => given ?? candidates.find((candidate) => candidate.id === chosenId) ?? null,
)

let destination = $ref<string | null>(presetDestination)
let mode = $ref<'change' | 'copy'>('change')
let copyIsPrivate = $ref<boolean>(true)

const source = $computed(() => workspace?.scope.toString() ?? null)
const isPrivate = $computed(() => workspace?.owner_id != null)

/** How a placement is named in prose, which for the engine root is where it is listed. */
function named(placement: string) {
  return placement === engineRoot ? 'Home' : placement
}

// The engine root is visible to anyone signed in, which the access cache holds no entry for.
function canView(placement: string) {
  return placement === engineRoot ? auth.user != null : access.canView(placement)
}

// Changing placement takes write access where the workspace is and, where it goes, whatever
// creating it there would: view for a private workspace and manage for a shared one. The server
// holds the same rule, this only says so before the click.
const blocker = $computed(() => {
  if (workspace == null || source == null || destination == null) {
    return null
  }
  if (!isWorkspaceWritable(workspace, auth.user?.id, access.canManage(source))) {
    return `Changing it requires manage access on ${named(source)}.`
  }
  if (isPrivate ? !canView(destination) : !access.canManage(destination)) {
    return `Changing it requires ${isPrivate ? 'view' : 'manage'} access on ${named(destination)}.`
  }

  return null
})

// A copy is a new workspace of the caller's own, so it takes no more than being able to see where
// it goes, and it may only be shared by someone who could create a shared one there.
const canCopy = $computed(() => destination != null && canView(destination))
const canShareCopy = $computed(() => destination != null && access.canManage(destination))

watch(
  () => blocker,
  (reason) => {
    if (reason != null) {
      mode = 'copy'
    }
  },
  { immediate: true },
)

// A copy keeps the original's visibility where it may, and is private where it may not be shared.
watch(
  [() => canShareCopy, () => workspace?.id],
  () => {
    copyIsPrivate = !canShareCopy || workspace?.owner_id != null
  },
  { immediate: true },
)

// Everyone signed in sees the engine root, so a shared workspace going there hides from no one.
const hidesFromSome = $computed(
  () => workspace != null && !isPrivate && mode === 'change' && destination !== engineRoot,
)

const unchanged = $computed(() => destination != null && destination === source)

// Counted on the pinned data, which is what lands at the destination either way.
const outside = $computed(() =>
  workspace == null || destination == null
    ? 0
    : widgetsOutside(pinWidgetAddresses(workspace.data, workspace.scope), destination),
)

const title = $computed(() => {
  if (destination === engineRoot) {
    return 'Make Workspace Global'
  }
  if (destination != null) {
    return `Associate Workspace with ${destination}`
  }

  return workspace != null && !workspace.scope.isEngine
    ? 'Reassociate Workspace'
    : 'Associate Workspace'
})

const submitLabel = $computed(() => {
  if (mode === 'copy') {
    return 'Copy'
  }

  return destination === engineRoot ? 'Make Global' : 'Associate'
})

const canSubmit = $computed(
  () =>
    workspace != null &&
    destination != null &&
    !unchanged &&
    (mode === 'copy' ? canCopy : blocker == null),
)

const workspaceOptions = $computed(() =>
  candidates.map((candidate) => ({
    label: candidate.name,
    value: candidate.id,
    icon: candidate.owner_id != null ? icons.privateWorkspace : icons.workspace,
  })),
)

function submit() {
  if (!canSubmit || workspace == null || destination == null) {
    return
  }

  emit('close', { workspace, destination, mode, isPrivate: copyIsPrivate })
}
</script>

<template>
  <c-modal
    :title="title"
    :ui="{ content: 'w-[520px] max-w-[95vw]' }"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <c-select
        v-if="given == null"
        class="mb-3 w-full"
        :items="workspaceOptions"
        label-key="label"
        :model-value="chosenId ?? undefined"
        placeholder="Choose a global workspace"
        value-key="value"
        @update:model-value="(id: string) => (chosenId = id)"
      />
      <c-text
        v-if="given == null && candidates.length === 0"
        class="mb-3 block"
        variant="description"
      >
        There are no global workspaces you can see.
      </c-text>
      <c-workspace-placement-select
        v-if="presetDestination == null"
        v-model="destination"
        class="mb-3"
        :current="source"
      />

      <template v-if="workspace != null && destination != null">
        <c-text v-if="unchanged" class="block" variant="description">
          "{{ workspace.name }}" is already
          {{ destination === engineRoot ? 'global' : `associated with ${destination}` }}.
        </c-text>
        <template v-else>
          <c-text class="mb-3 block" variant="body2">
            <template v-if="destination === engineRoot">
              "{{ workspace.name }}" stops belonging to
              <c-text inline variant="mono-xs">{{ source }}</c-text> and is listed on Home.
            </template>
            <template v-else>
              "{{ workspace.name }}" is listed on
              <c-text inline variant="mono-xs">{{ destination }}</c-text>
              instead of
              <template v-if="source === engineRoot">Home.</template>
              <template v-else
                ><c-text inline variant="mono-xs">{{ source }}</c-text
                >.</template
              >
            </template>
            Its widgets keep pointing at the same components.
          </c-text>

          <c-radio-group
            v-model="mode"
            :items="[
              { label: 'Change this workspace.', value: 'change', disabled: blocker != null },
              { label: 'Make a copy, leaving this one where it is.', value: 'copy' },
            ]"
          />
          <c-text v-if="blocker != null" class="mt-2 block pl-2" variant="description">
            {{ blocker }}
          </c-text>

          <c-text v-if="hidesFromSome" class="mt-3 block italic text-warning" variant="description">
            It disappears for anyone who cannot see
            <c-text inline variant="mono-xs">{{ destination }}</c-text
            >, along with any unsaved changes they hold against it, and appears for everyone who
            can.
          </c-text>
          <c-text
            v-else-if="mode === 'change' && !isPrivate"
            class="mt-3 block"
            variant="description"
          >
            It appears for everyone signed in.
          </c-text>

          <template v-if="mode === 'copy'">
            <c-select
              v-if="canShareCopy"
              v-model="copyIsPrivate"
              class="mt-3 w-full"
              :icon="copyIsPrivate ? icons.privateWorkspace : icons.workspace"
              :items="[
                { label: 'Shared', value: false, icon: icons.workspace },
                { label: 'Private', value: true, icon: icons.privateWorkspace },
              ]"
              label-key="label"
              value-key="value"
            />
            <c-text v-else-if="canCopy" class="mt-3 block" variant="description">
              <c-icon class="mr-1 align-text-bottom" :name="icons.privateWorkspace" size="14" />
              The copy is private to you. Sharing it requires manage access on
              {{ named(destination) }}.
            </c-text>
            <c-text v-else class="mt-3 block" variant="description">
              Copying requires view access on {{ named(destination) }}.
            </c-text>
          </template>

          <c-text v-if="outside > 0" class="mt-3 block text-warning" variant="description">
            {{ outside === 1 ? 'One widget points' : `${outside} widgets point` }} at components
            outside {{ destination }} and will show nothing there.
          </c-text>
        </template>
      </template>
    </template>
    <template #footer>
      <div class="flex w-full gap-2">
        <c-button
          block
          class="flex-1"
          color="neutral"
          :icon="icons.cancel"
          label="Cancel"
          variant="soft"
          @click="emit('close', false)"
        />
        <c-button
          block
          class="flex-1"
          :color="hidesFromSome ? 'warning' : 'primary'"
          :disabled="!canSubmit"
          :icon="icons.confirm"
          :label="submitLabel"
          @click="submit()"
        />
      </div>
    </template>
  </c-modal>
</template>
