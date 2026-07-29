<script lang="ts" setup>
import { v7 } from 'uuid'

import CommonText from '@/components/CommonText.vue'
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import {
  createWidget,
  getWidgetInfo,
  resolveWidgetWidths,
  widgetInfos,
  widgetWidthSubdivisions,
  CarouselSlide,
  CarouselWidget,
  WidgetRow,
  WidgetType,
} from '@/workspace'

const { widget } = defineProps<{
  widget: CarouselWidget
}>()

let editing = $ref<string | null>(null)

function addSlide() {
  const slide: CarouselSlide = { id: v7(), name: `Slide ${widget.slides.length + 1}`, layout: [] }
  widget.slides = [...widget.slides, slide]
  editing = slide.id
}

function deleteSlide(slide: CarouselSlide) {
  widget.slides = widget.slides.filter((current) => current !== slide)
}

function moveSlide(slide: CarouselSlide, by: number) {
  const from = widget.slides.indexOf(slide)
  const to = from + by
  if (from === -1 || to < 0 || to >= widget.slides.length) {
    return
  }

  const slides = [...widget.slides]
  slides.splice(from, 1)
  slides.splice(to, 0, slide)
  widget.slides = slides
}

// A widget added to a slide arrives in a row of its own, which is the one arrangement that needs no
// choice made about it. Anything else is reached by moving it into a row beside another.
function addWidget(slide: CarouselSlide, type: WidgetType) {
  const added = createWidget(type)
  added.width = widgetWidthSubdivisions

  const row: WidgetRow = {
    id: v7(),
    height: getWidgetInfo(type).options.minHeight,
    collapsed: false,
    widgets: [added],
  }
  slide.layout = [...slide.layout, row]
}

function deleteWidget(slide: CarouselSlide, row: WidgetRow, index: number) {
  const remaining = row.widgets.filter((_, at) => at !== index)
  if (remaining.length === 0) {
    slide.layout = slide.layout.filter((current) => current !== row)
    return
  }

  resolveWidgetWidths(remaining)
  row.widgets = remaining
}

/** Move a widget between the rows of a slide, joining the one it lands in or opening its own. */
function moveWidget(slide: CarouselSlide, row: WidgetRow, index: number, by: number) {
  const at = slide.layout.indexOf(row)
  const to = at + by
  if (at === -1 || to < 0 || to > slide.layout.length - 1) {
    return
  }

  const moved = row.widgets[index]
  const remaining = row.widgets.filter((_, position) => position !== index)
  const destination = slide.layout[to]

  const joined = [...destination.widgets, moved]
  moved.width = Math.min(widgetWidthSubdivisions / joined.length, moved.width)
  resolveWidgetWidths(joined, joined.length - 1)
  destination.widgets = joined

  if (remaining.length === 0) {
    slide.layout = slide.layout.filter((current) => current !== row)
  } else {
    resolveWidgetWidths(remaining)
    row.widgets = remaining
  }
}

function splitWidget(slide: CarouselSlide, row: WidgetRow, index: number) {
  if (row.widgets.length < 2) {
    return
  }

  const moved = row.widgets[index]
  const remaining = row.widgets.filter((_, position) => position !== index)
  resolveWidgetWidths(remaining)
  row.widgets = remaining

  moved.width = widgetWidthSubdivisions
  const layout = [...slide.layout]
  layout.splice(slide.layout.indexOf(row) + 1, 0, {
    id: v7(),
    height: row.height,
    collapsed: false,
    widgets: [moved],
  })
  slide.layout = layout
}
</script>

<template>
  <div class="q-pa-md">
    <common-text class="q-mb-sm" variant="title1">{{ widget.name }}</common-text>
    <div class="q-col-gutter-sm q-mb-md row">
      <div class="col-6">
        <schema-form-value
          v-model="widget.interval"
          :schema="{
            type: 'integer',
            title: 'Seconds Per Slide',
            minimum: 1,
            maximum: 3600,
          }"
        />
      </div>
      <div class="col-6 items-center row">
        <q-toggle v-model="widget.autoplay" label="Advance On Its Own" />
      </div>
    </div>

    <common-text class="q-mb-sm" variant="title2">Slides</common-text>
    <common-text v-if="widget.slides.length === 0" class="q-mb-sm" variant="description">
      A carousel shows one slide at a time, and each slide holds a layout of its own.
    </common-text>

    <q-card v-for="(slide, at) in widget.slides" :key="slide.id" bordered class="q-mb-sm" flat>
      <div :class="[$style.slideHeader, 'items-center', 'no-wrap', 'q-px-sm', 'q-py-xs', 'row']">
        <common-text variant="th">
          <inline-name-edit
            :editing="editing === slide.id"
            :name="slide.name"
            @rename="(value: string) => (slide.name = value)"
            @update:editing="(value: boolean) => (editing = value ? slide.id : null)"
          />
        </common-text>
        <q-space />
        <q-btn dense flat :icon="icons.rename" round size="9px" @click="editing = slide.id">
          <q-tooltip class="bg-primary">Rename</q-tooltip>
        </q-btn>
        <q-btn
          dense
          :disable="at === 0"
          flat
          :icon="icons.menuUp"
          round
          size="9px"
          @click="moveSlide(slide, -1)"
        >
          <q-tooltip class="bg-primary">Move Up</q-tooltip>
        </q-btn>
        <q-btn
          dense
          :disable="at === widget.slides.length - 1"
          flat
          :icon="icons.menuDown"
          round
          size="9px"
          @click="moveSlide(slide, 1)"
        >
          <q-tooltip class="bg-primary">Move Down</q-tooltip>
        </q-btn>
        <q-btn dense flat :icon="icons.delete" round size="9px" @click="deleteSlide(slide)">
          <q-tooltip class="bg-negative">Delete Slide</q-tooltip>
        </q-btn>
      </div>
      <q-separator />
      <div class="q-pa-sm">
        <common-text v-if="slide.layout.length === 0" variant="description">
          Nothing on this slide yet.
        </common-text>
        <div
          v-for="(row, rowAt) in slide.layout"
          :key="row.id"
          :class="[$style.row, 'q-mb-xs', 'q-pa-xs']"
        >
          <div
            v-for="(current, index) in row.widgets"
            :key="current.id"
            class="items-center no-wrap row"
          >
            <common-text :class="$style.widgetName" variant="body2">
              {{ current.name !== '' ? current.name : getWidgetInfo(current.type).name }}
            </common-text>
            <q-space />
            <q-btn
              dense
              :disable="rowAt === 0"
              flat
              :icon="icons.menuUp"
              round
              size="9px"
              @click="moveWidget(slide, row, index, -1)"
            >
              <q-tooltip class="bg-primary">Join The Row Above</q-tooltip>
            </q-btn>
            <q-btn
              dense
              :disable="rowAt === slide.layout.length - 1"
              flat
              :icon="icons.menuDown"
              round
              size="9px"
              @click="moveWidget(slide, row, index, 1)"
            >
              <q-tooltip class="bg-primary">Join The Row Below</q-tooltip>
            </q-btn>
            <q-btn
              dense
              :disable="row.widgets.length < 2"
              flat
              :icon="icons.tabUnselected"
              round
              size="9px"
              @click="splitWidget(slide, row, index)"
            >
              <q-tooltip class="bg-primary">Give It A Row Of Its Own</q-tooltip>
            </q-btn>
            <q-btn
              dense
              flat
              :icon="icons.delete"
              round
              size="9px"
              @click="deleteWidget(slide, row, index)"
            >
              <q-tooltip class="bg-negative">Remove</q-tooltip>
            </q-btn>
          </div>
        </div>
        <q-btn class="q-mt-xs" dense flat :icon="icons.add" label="Add Widget" no-caps size="sm">
          <q-menu>
            <q-card bordered>
              <q-list dense>
                <q-item
                  v-for="option in widgetInfos"
                  :key="option.type"
                  v-close-popup
                  clickable
                  @click="addWidget(slide, option.type)"
                >
                  <q-item-section>
                    <q-item-label>{{ option.name }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </q-menu>
        </q-btn>
      </div>
    </q-card>

    <q-btn
      color="primary"
      dense
      flat
      :icon="icons.add"
      label="Add Slide"
      no-caps
      @click="addSlide"
    />
  </div>
</template>

<style lang="scss" module>
:global(.light) .slideHeader {
  background-color: rgba(0, 0, 0, 0.03);
}

:global(.dark) .slideHeader {
  background-color: rgba(255, 255, 255, 0.05);
}

// A row of the slide, drawn as one so that widgets sharing a row read as sharing it.
.row {
  border-left: 2px solid $primary;
  border-radius: 2px;
}

.widgetName {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
