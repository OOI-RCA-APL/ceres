<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import WorkspaceWidgetRestricted from '@/components/WorkspaceWidgetRestricted.vue'
import { getWidgetInfo, widgetWidthSubdivisions, Widget, WidgetRow } from '@/workspace'

const { layout } = defineProps<{
  layout: WidgetRow[]
}>()

// Row heights are read as shares of whatever room the slide is given rather than as pixels, so a
// slide always fills its carousel exactly however tall the carousel happens to be. A row keeps the
// proportions it was laid out with without ever needing a scrollbar of its own.
function getRowStyle(row: WidgetRow) {
  return { flex: `${Math.max(row.height, 1)} 1 0` }
}

function getWidgetStyle(widget: Widget, isLast: boolean) {
  const share = `${(widget.width / widgetWidthSubdivisions) * 100}%`

  return isLast ? { minWidth: share } : { maxWidth: share, minWidth: share }
}
</script>

<template>
  <div :class="[$style.root, 'column', 'full-height', 'no-wrap']">
    <div
      v-for="row in layout"
      :key="row.id"
      class="full-width no-wrap row"
      :style="getRowStyle(row)"
    >
      <div
        v-for="(widget, index) in row.widgets"
        :key="widget.id"
        :class="[
          index < row.widgets.length - 1 ? 'col-shrink' : 'col-grow',
          'relative-position',
          row.widgets.length === 1
            ? ''
            : index === 0
            ? 'q-pr-xs'
            : index === row.widgets.length - 1
            ? 'q-pl-xs'
            : 'q-px-xs',
        ]"
        :style="getWidgetStyle(widget, index === row.widgets.length - 1)"
      >
        <q-card bordered class="column full-height" flat>
          <!-- Named but not otherwise dressed. A widget on a slide is being read rather than
          arranged, so it carries none of the handles a widget in a workspace does. -->
          <div v-if="widget.name !== ''" :class="[$style.header, 'q-px-sm', 'q-py-xs']">
            <common-text :class="$style.name" variant="th">{{ widget.name }}</common-text>
          </div>
          <q-separator v-if="widget.name !== ''" />
          <div
            :class="[
              $style.content,
              'col-grow',
              'overflow-auto',
              getWidgetInfo(widget.type).options.paddingClass,
            ]"
          >
            <workspace-widget-restricted v-if="widget.restricted" :widget />
            <component
              :is="getWidgetInfo(widget.type).component as any"
              v-else
              :class="getWidgetInfo(widget.type).options.fullHeight && 'full-height'"
              :widget="widget"
            />
          </div>
        </q-card>
      </div>
    </div>
  </div>
</template>

<style lang="scss" module>
@use 'sass:color';

.root {
  gap: 8px;
}

:global(.light) .header {
  background-color: color.adjust(white, $lightness: -1%);
}

.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content {
  height: 0 !important;
}

:global(.dark) .content {
  background-color: $darker;
}
</style>
