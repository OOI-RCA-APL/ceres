<script lang="ts">
import type { BreadcrumbItem } from '@nuxt/ui'

import { type FilePlace, fileComponentChain, fileComponentFolderName } from '@/api/files'
import type { ValueHistory } from '@/history'
import icons from '@/icons'

/** The breadcrumb beside Back and Forward, in the file views' smaller text. */
export const FILE_BREADCRUMB_UI = {
  link: 'text-xs',
  linkLeadingIcon: 'size-4',
  separatorIcon: 'size-4',
}

/** The crumbs of the component folders from below `root` down to `component`, none without one.
`open` gives each crumb its link or click. */
export function fileFolderCrumbs(
  component: string | null,
  root: string | null,
  open: (folder: string) => Partial<BreadcrumbItem>,
): BreadcrumbItem[] {
  return (component == null ? [] : fileComponentChain(component, root)).map((folder) => ({
    label: fileComponentFolderName(folder),
    icon: icons.components,
    ...open(folder),
  }))
}
</script>

<script lang="ts" setup>
const { history } = defineProps<{
  history: ValueHistory<FilePlace>
}>()

const emit = defineEmits<{
  /** Back or Forward picked `place`, which the caller opens. */
  go: [place: FilePlace]
}>()

function step(place: FilePlace | undefined) {
  if (place != null) {
    emit('go', place)
  }
}
</script>

<template>
  <c-field-group class="shrink-0">
    <c-tooltip text="Back">
      <c-button
        aria-label="Back"
        color="neutral"
        :disabled="!history.canBack"
        :icon="icons.chevronLeft"
        size="xs"
        variant="outline"
        @click="step(history.back())"
      />
    </c-tooltip>
    <c-tooltip text="Forward">
      <c-button
        aria-label="Forward"
        color="neutral"
        :disabled="!history.canForward"
        :icon="icons.chevronRight"
        size="xs"
        variant="outline"
        @click="step(history.forward())"
      />
    </c-tooltip>
  </c-field-group>
</template>
