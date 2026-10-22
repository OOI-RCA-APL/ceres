<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import type { FilesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: FilesWidget
}>()

const engine = useEngine()

const mountsQuery = useQuery({
  queryKey: ['files', 'mounts'],
  queryFn: () => engine.files.getMounts(),
})
const mounts = $computed(() => mountsQuery.data.value ?? [])
</script>

<template>
  <c-workspace-widget-settings :widget>
    <c-schema-form-value
      v-model="widget.mount"
      :schema="{
        type: 'string',
        title: 'Folder',
        enum: mounts.map((current) => current.id),
        enumLabels: mounts.map((current) =>
          current.component == null ? current.label : `${current.label} (${current.component})`,
        ),
        optional: true,
      }"
    />
  </c-workspace-widget-settings>
</template>
