<script lang="ts" setup>
import { useConfig } from '@/api/config'
import CommonText from '@/components/CommonText.vue'
import UtcClock from '@/components/UtcClock.vue'
import constants from '@/constants'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useNavigation } from '@/navigation'

const drawer = useDrawer()
const navigation = useNavigation()
const config = useConfig()
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
        @click="drawer.toggle()"
      />
      <q-toolbar-title class="cursor-pointer" @click="navigation.go('/')">
        <common-text variant="title1">
          {{ config.console.title ?? constants.defaultTitle }}
        </common-text>
      </q-toolbar-title>
      <utc-clock />
    </q-toolbar>
    <q-separator />
  </q-header>
</template>
