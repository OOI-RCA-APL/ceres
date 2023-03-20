<template>
  <div>
    <schema-form v-model="value" :schema="schema" />
  </div>
</template>

<script lang="ts" setup>
import SchemaForm from '@/components/SchemaForm.vue'
import { Schema } from '@/json-schema'

let value = $shallowRef({
  name: 'Sarah',
})

const schema: Schema = {
  type: 'object',
  title: 'Info',
  definitions: {
    Dimensions: {
      type: 'object',
      properties: {
        width: {
          type: 'number',
          title: 'Width',
        },
        height: {
          type: 'number',
          title: 'Height',
        },
      },
      required: ['width', 'height'],
    },
  },
  properties: {
    name: {
      type: 'string',
      title: 'Name',
    },
    age: {
      type: 'integer',
      title: 'Age',
      maximum: 50,
      default: 5,
    },
    alive: {
      type: 'boolean',
      title: 'Alive',
    },
    dimensions: {
      $ref: '#/definitions/Dimensions',
      title: 'Age',
    },
    strings: {
      type: 'array',
      title: 'Strings',
      items: {
        type: 'string',
      },
      default: ['Hello'],
    },
  },
  required: ['name'],
}
</script>
