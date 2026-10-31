<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { computed, watch } from 'vue'

import { type FilePlace, fileMountComponent, filePlace, useFileHistory } from '@/api/files'
import { FILE_BREADCRUMB_UI, fileFolderCrumbs } from '@/components/c-file-history.vue'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { type FilesWidget, filesWidgetRoot, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: FilesWidget
}>()

const emit = defineEmits<{
  settingsRequested: []
}>()

const workspace = useWorkspace()

/** The component whose mounts the widget lists, null for every mount. */
const root = $computed(() => filesWidgetRoot(widget.component, workspace.scope))

/** Where the widget opens, the folder of `root` when `mount` is null. */
const start = $computed(() => filePlace(widget.mount ?? null, widget.path, root))

// Where the widget is belongs to this browser and not to the workspace, so two people sharing a
// workspace each keep their own place in it. `start` records where the widget opened, so a new
// choice in its settings brings every browser back to it.
const persisted = usePersisted({
  schema: ({ object, string, array }) =>
    object({
      start: string().nullable().default(null),
      mount: string().nullable().default(null),
      component: string().nullable().default(null),
      path: array(string()).default([]),
    }),
  methods: computed(() => [{ type: 'local-storage' as const, key: ['files-widget', widget.id] }]),
})

const startKey = $computed(() => JSON.stringify([root, start.mount, start.path]))

const place = $computed(() =>
  persisted.start === startKey
    ? filePlace(persisted.mount, persisted.path, persisted.component)
    : start,
)

function go({ mount, component, path }: FilePlace) {
  persisted.start = startKey
  persisted.mount = mount
  persisted.component = component
  persisted.path = path
}

const path = $computed({
  get: () => place.path,
  set: (value: string[]) => go(filePlace(place.mount, value)),
})

// Back and Forward run across the list of mounts and every mount opened from it, so the history
// sits outside the browser, which remounts for each mount.
const viewKey = `widget/${widget.id}`
const history = useFileHistory(viewKey)
watch(
  () => place,
  (value) => history.record(value),
  { immediate: true },
)

/** The list's crumb, named for the component it narrows to. */
const listLabel = $computed(() => root ?? 'Files')

/** The crumbs from the list down to the folder of `address` below `root`. */
function folderCrumbs(address: string | null): BreadcrumbItem[] {
  return [
    { label: listLabel, icon: icons.files, onClick: () => go(filePlace(null, [], root)) },
    ...fileFolderCrumbs(address, root, (folder) => ({
      onClick: () => go(filePlace(null, [], folder)),
    })),
  ]
}

const home = $computed(() =>
  place.mount == null ? [] : folderCrumbs(fileMountComponent(place.mount)),
)
</script>

<template>
  <div class="h-full p-2">
    <c-file-browser
      v-if="place.mount != null"
      :key="place.mount"
      v-model:path="path"
      :history
      :home
      :mount="place.mount"
      :view-key
      @go="go"
      @preview="path = $event"
    />
    <div v-else class="flex h-full min-h-0 flex-col gap-3 overflow-auto">
      <div class="flex shrink-0 items-center gap-2">
        <c-file-history :history @go="go" />
        <c-breadcrumb
          class="min-w-0"
          :items="folderCrumbs(place.component)"
          :ui="FILE_BREADCRUMB_UI"
        />
      </div>
      <c-file-mounts
        :linked="false"
        :root="place.component"
        @open="go(filePlace($event.id))"
        @open-folder="go(filePlace(null, [], $event))"
      >
        <template #empty>
          <div class="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
            <c-icon class="text-dimmed" :name="icons.folderOpen" size="48" />
            <c-text variant="title2">No File Mounts</c-text>
            <c-text class="text-muted max-w-md" variant="body3">
              <template v-if="root != null">
                {{ root }} and its subcomponents have no file mounts. The widget's settings can
                point it at another component.
              </template>
              <template v-else>No file mounts are shared with you.</template>
            </c-text>
            <c-button
              color="neutral"
              :icon="icons.settings"
              label="Widget Settings"
              size="sm"
              variant="outline"
              @click="emit('settingsRequested')"
            />
          </div>
        </template>
      </c-file-mounts>
    </div>
  </div>
</template>
