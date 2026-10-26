<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { isFileMountUnder } from '@/api/files'
import { type FilesWidget, filesWidgetRoot, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: FilesWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const mountsQuery = useQuery({
  queryKey: ['files', 'mounts'],
  queryFn: () => engine.files.getMounts(),
})

// The same mounts the widget lists, so it never opens on one its own list leaves out.
const mounts = $computed(() => {
  const root = filesWidgetRoot(widget.component, workspace.scope)
  return (mountsQuery.data.value ?? []).filter((current) => isFileMountUnder(current, root))
})

/** The directory under the mount, typed as a path with slashes. */
const directory = $computed({
  get: () => widget.path.join('/'),
  set: (value: string | null | undefined) => {
    widget.path = (value ?? '').split('/').filter((name) => name !== '')
  },
})
</script>

<template>
  <c-workspace-widget-settings :widget>
    <c-workspace-address-select
      :model-value="widget.component ?? null"
      root-label="All Components"
      @update:model-value="(value) => (widget.component = value)"
    />
    <c-schema-form-value
      v-model="widget.mount"
      :schema="{
        type: 'string',
        title: 'Open On',
        description: 'The file mount the widget opens on, or the list of file mounts when empty.',
        enum: mounts.map((current) => current.id),
        enumLabels: mounts.map((current) =>
          current.component == null ? current.label : `${current.label} (${current.component})`,
        ),
        optional: true,
      }"
    />
    <c-schema-form-value
      v-if="widget.mount != null"
      v-model="directory"
      :schema="{
        type: 'string',
        title: 'Folder',
        description: 'A folder inside the file mount to open on, like 2026/10.',
        optional: true,
      }"
    />
  </c-workspace-widget-settings>
</template>
