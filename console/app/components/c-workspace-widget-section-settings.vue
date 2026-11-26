<script lang="ts" setup>
import { useLayoutArrange } from '@/layout-arrange'
import { type LayoutArrange, layoutExpandOptions, type SectionWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: SectionWidget
}>()

const layoutArrange = useLayoutArrange()

// Creation and parsing both hold a section to exactly one page.
const page = $computed(() => widget.pages[0]!)

// Arranging can ask first, so the select shows the page's own value until it changes.
const arrange = $computed({
  get: () => page.arrange,
  set: (value: LayoutArrange) => layoutArrange.arrange(page, value),
})
</script>

<template>
  <c-workspace-widget-settings :widget>
    <c-form-field class="mb-2" label="Arrange">
      <c-select
        v-model="arrange"
        class="w-full"
        :items="layoutArrange.options(page)"
        label-key="label"
        value-key="value"
      />
    </c-form-field>
    <!-- A flex page wraps at its widgets' own sizes, so it has no rows to stretch. -->
    <div v-if="page.arrange === 'rows'" class="flex flex-nowrap items-end gap-2">
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
