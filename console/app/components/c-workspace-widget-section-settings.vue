<script lang="ts" setup>
import { layoutExpandOptions } from '@/workspace'
import type { SectionWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: SectionWidget
}>()
</script>

<template>
  <c-workspace-widget-settings :widget>
    <div class="flex flex-nowrap items-end gap-2">
      <c-form-field class="grow" label="Fill Section Height">
        <c-select
          v-model="widget.expand"
          class="w-full"
          :items="layoutExpandOptions"
          label-key="label"
          value-key="value"
        />
      </c-form-field>
      <!-- Shrinking only applies to rows stretched to fill, as on the tab strip's menu. -->
      <c-checkbox
        v-if="widget.expand !== 'none'"
        v-model="widget.shrink"
        class="pb-1.5"
        label="Shrink"
        size="sm"
      />
    </div>
  </c-workspace-widget-settings>
</template>
