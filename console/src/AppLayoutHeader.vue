<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import UtcClock from '@/components/UtcClock.vue'
import constants from '@/constants'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useRouter } from 'vue-router'

const drawer = useDrawer()
const router = useRouter()
</script>

<template>
  <q-header class="bg-primary">
    <q-toolbar class="no-wrap">
      <q-btn
        dense
        flat
        :icon="icons.menu"
        round
        style="margin-left: -2px; margin-right: 14px"
        @click="drawer.isOpen = !drawer.isOpen"
      />
      <q-toolbar-title class="cursor-pointer" @click="router.push('/')">
        <common-text variant="title1">{{ constants.appName }}</common-text>
      </q-toolbar-title>
      <utc-clock />
    </q-toolbar>
    <q-separator />
  </q-header>
</template>
