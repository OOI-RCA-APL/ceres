<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import type { FilesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: FilesWidget
}>()

const engine = useEngine()

const rootsQuery = useQuery({
  queryKey: ['files', 'roots'],
  queryFn: () => engine.files.getRoots(),
})
const roots = $computed(() => rootsQuery.data.value ?? [])
</script>

<template>
  <c-workspace-widget-settings :widget>
    <c-schema-form-value
      v-model="widget.root"
      :schema="{
        type: 'string',
        title: 'Root',
        enum: roots.map((current) => current.id),
        enumLabels: roots.map((current) =>
          current.component == null ? current.label : `${current.label} (${current.component})`,
        ),
        optional: true,
      }"
    />
  </c-workspace-widget-settings>
</template>
