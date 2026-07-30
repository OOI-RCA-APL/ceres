<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { CarouselWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: CarouselWidget
}>()
</script>

<template>
  <div class="q-pa-md">
    <common-text class="q-mb-sm" variant="title1">{{ widget.name }}</common-text>
    <div class="q-col-gutter-sm row">
      <!-- Whether it advances at all comes before how long it waits, since the interval means
      nothing until it does. -->
      <div class="col-6 items-center row">
        <q-checkbox v-model="widget.autoplay" dense label="Autoplay" />
      </div>
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
    </div>
  </div>
</template>
