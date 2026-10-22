<script lang="ts" setup>
import { computed } from 'vue'

import icons from '@/icons'
import { usePersisted } from '@/persistence'
import type { FilesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: FilesWidget
}>()

const emit = defineEmits<{
  settingsRequested: []
}>()

// The open directory belongs to this browser and not to the workspace, so two people sharing a
// workspace each keep their own place in it.
const persisted = usePersisted({
  schema: ({ object, string, array }) =>
    object({ mount: string().nullable().default(null), path: array(string()).default([]) }),
  methods: computed(() => [{ type: 'local-storage' as const, key: ['files-widget', widget.id] }]),
})

// A place stored under another mount means nothing in this one.
const path = $computed({
  get: () => (persisted.mount === widget.mount ? persisted.path : []),
  set: (value: string[]) => {
    persisted.mount = widget.mount ?? null
    persisted.path = value
  },
})
</script>

<template>
  <div class="h-full p-2">
    <c-file-browser v-if="widget.mount != null" v-model:path="path" :mount="widget.mount" />
    <div v-else class="flex h-full items-center justify-center text-center">
      <c-tooltip text="Choose Files">
        <c-button
          aria-label="Choose Files"
          class="rounded-full"
          color="primary"
          :icon="icons.folderNew"
          @click="emit('settingsRequested')"
        />
      </c-tooltip>
    </div>
  </div>
</template>
