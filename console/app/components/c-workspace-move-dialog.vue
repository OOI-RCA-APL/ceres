<script lang="ts" setup>
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import icons from '@/icons'
import { isWorkspaceWritable, type Workspace } from '@/workspace'
import { pinWidgetAddresses, widgetsOutside } from '@/workspace/association'

export type WorkspaceMoveDialogProps = {
  /** The workspace to move. Without one, the dialog asks which of `candidates`. */
  workspace?: Workspace | null
  candidates?: Workspace[]
  /** Where it goes, already chosen by a drop or by the page it was asked from. */
  destination?: string | null
}

export type WorkspaceMove = {
  workspace: Workspace
  destination: string
  /** Whether a copy is made there, leaving the original where it is. */
  copy: boolean
  /** For a copy, whether it is the caller's own. */
  isPrivate: boolean
}

const {
  workspace: given = null,
  candidates = [],
  destination: presetDestination = null,
} = defineProps<WorkspaceMoveDialogProps>()

/** Closes with the chosen move, or `false` for a cancel. */
const emit = defineEmits<{ close: [WorkspaceMove | false] }>()

const access = useAccess()
const auth = useAuth()

let chosenId = $ref<string | null>(given?.id ?? null)
const workspace = $computed(
  () => given ?? candidates.find((candidate) => candidate.id === chosenId) ?? null,
)

let destination = $ref<string | null>(presetDestination)
let copy = $ref(false)
let copyIsPrivate = $ref<boolean>(true)

const source = $computed(() => workspace?.scope.toString() ?? null)
const isPrivate = $computed(() => workspace?.owner_id != null)

/** How a location reads in prose and in lists. */
function named(location: string) {
  return location === engineRoot ? 'Global' : location
}

// The engine root is visible to anyone signed in, which the access cache holds no entry for.
function canView(location: string) {
  return location === engineRoot ? auth.user != null : access.canView(location)
}

// Moving takes write access where the workspace is and, where it goes, whatever creating it there
// would: view for a private workspace and manage for a shared one. The server holds the same rule,
// this only says so before the click.
const blocker = $computed(() => {
  if (workspace == null || source == null || destination == null) {
    return null
  }
  if (!isWorkspaceWritable(workspace, auth.user?.id, access.canManage(source))) {
    return `Moving it requires manage access on ${named(source)}.`
  }
  if (isPrivate ? !canView(destination) : !access.canManage(destination)) {
    return `Moving it requires ${isPrivate ? 'view' : 'manage'} access on ${named(destination)}.`
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
      copy = true
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
  () => workspace != null && !isPrivate && !copy && destination !== engineRoot,
)

const unchanged = $computed(() => destination != null && destination === source)

// Counted on the pinned data, which is what lands at the destination either way.
const outside = $computed(() =>
  workspace == null || destination == null
    ? 0
    : widgetsOutside(pinWidgetAddresses(workspace.data, workspace.scope), destination),
)

const title = $computed(() =>
  presetDestination == null ? 'Move Workspace' : `Move Workspace to ${named(presetDestination)}`,
)

const canSubmit = $computed(
  () =>
    workspace != null && destination != null && !unchanged && (copy ? canCopy : blocker == null),
)

function submit() {
  if (!canSubmit || workspace == null || destination == null) {
    return
  }

  emit('close', { workspace, destination, copy, isPrivate: copyIsPrivate })
}
</script>

<template>
  <c-modal
    :title="title"
    :ui="{ content: 'w-[520px] max-w-[95vw]' }"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <!-- Once one is picked the list folds to that one, so the rest of the dialog has room. -->
      <template v-if="given == null">
        <div
          v-if="workspace != null"
          class="mb-3 flex items-center gap-2 rounded-md border border-default px-2 py-1.5"
        >
          <c-icon
            class="shrink-0"
            :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
            size="18"
          />
          <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ workspace.name }}</c-text>
          <c-text class="opacity-60" variant="mono-xs">{{ named(source as string) }}</c-text>
          <c-button label="Change" size="xs" variant="ghost" @click="chosenId = null" />
        </div>
        <c-workspace-chooser
          v-else
          class="mb-3 rounded-md border border-default"
          empty="There are no other workspaces you can see."
          :items="candidates"
          @select="(chosen: Workspace) => (chosenId = chosen.id)"
        />
      </template>
      <template v-if="presetDestination == null">
        <c-text class="mb-1 block" variant="description">Location</c-text>
        <c-workspace-location-select v-model="destination" class="mb-3" :current="source" />
      </template>

      <template v-if="workspace != null && destination != null && source != null">
        <c-text v-if="unchanged" class="block" variant="description">
          "{{ workspace.name }}" is already in {{ named(destination) }}.
        </c-text>
        <template v-else>
          <c-text class="text-toned mb-3 block" variant="body3">
            <template v-if="copy">
              A copy of "{{ workspace.name }}" will be made in {{ named(destination) }}, and the
              original will stay in {{ named(source) }}.
            </template>
            <template v-else>
              "{{ workspace.name }}" will move from {{ named(source) }} to {{ named(destination) }}.
            </template>
            Its widgets will keep pointing at the same components.
          </c-text>

          <c-checkbox v-model="copy" :disabled="blocker != null" label="Make a Copy" />
          <c-text v-if="blocker != null" class="mt-2 block" variant="description">
            {{ blocker }}
          </c-text>

          <c-text v-if="hidesFromSome" class="mt-3 block text-warning" variant="description">
            It disappears for anyone who cannot see {{ destination }}, along with any unsaved
            changes they hold against it, and appears for everyone who can.
          </c-text>
          <c-text v-else-if="!copy && !isPrivate" class="mt-3 block" variant="description">
            It appears for everyone signed in.
          </c-text>

          <template v-if="copy">
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
          :label="copy ? 'Copy' : 'Move'"
          @click="submit()"
        />
      </div>
    </template>
  </c-modal>
</template>
